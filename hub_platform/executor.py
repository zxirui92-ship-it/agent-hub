"""Generic dependency executor with explicit, in-process approval continuation."""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from common.contracts import (AgentRequest, AgentResult, ApprovalDecision, ExecutionPlan,
    ExecutionReport, LiteralBinding, StepRecord, StepState, TraceEvent)
from common.errors import ErrorCode, ServiceError
from hub_platform.errors import HubError
from hub_platform.registry import CapabilityRegistry
from hub_platform.schema import validate_data
from hub_platform.validator import PlanValidator


@dataclass
class _Run:
    plan: ExecutionPlan
    task_id: str
    trace_id: str
    context: dict
    records: dict[str, StepRecord]
    events: list[TraceEvent] = field(default_factory=list)


class Executor:
    def __init__(self, registry: CapabilityRegistry, max_steps: int = 32) -> None:
        self.registry = registry
        self.validator = PlanValidator(registry, max_steps)
        self._waiting: dict[str, _Run] = {}

    def execute(self, raw: ExecutionPlan | dict[str, Any], *, task_id: str | None = None,
                trace_id: str | None = None, context: dict[str, Any] | None = None) -> ExecutionReport:
        plan = self.validator.validate(raw).model_copy(deep=True)
        task_id = task_id or f"task-{uuid4().hex[:12]}"
        if task_id in self._waiting:
            raise HubError(ErrorCode.INVALID_INPUT, '任务尚在等待，请显式恢复或使用新的 task_id')
        run = _Run(plan, task_id, trace_id or f"trace-{uuid4().hex[:16]}", deepcopy(context or {}),
                   {s.step_id: StepRecord(step_id=s.step_id, capability_id=s.capability_id,
                                         depends_on=s.depends_on) for s in plan.steps})
        for record in run.records.values():
            self._transition(run, record, StepState.PENDING, '已加入执行计划')
        return self._drain(run)

    def discard(self, task_id: str) -> None:
        """Forget platform continuation state; never approve or restart a module."""
        self._waiting.pop(task_id, None)

    def resume(self, task_id: str, step_id: str, decision: ApprovalDecision | dict) -> ExecutionReport:
        """Resume one waiting step and drain only newly ready pending steps.

        Sequential calls within the same Executor/module instances are supported.
        No process persistence, implicit retry, or deserialized report execution.
        """
        run = self._waiting.get(task_id)
        if run is None:
            raise HubError(ErrorCode.NOT_FOUND, '待续任务不存在、已结束或进程已重启', step_id)
        record = run.records.get(step_id)
        if record is None or record.status != StepState.WAITING_APPROVAL:
            raise HubError(ErrorCode.INVALID_INPUT, '目标步骤不在等待审批', step_id)
        try:
            decision = ApprovalDecision.model_validate(decision.model_dump() if isinstance(decision, ApprovalDecision) else decision)
        except ValidationError as exc:
            raise HubError(ErrorCode.INVALID_INPUT, '审批需显式布尔 approved/material_complete 和非空 reviewer', step_id) from exc
        manifest = self.registry.get_manifest(record.capability_id)
        module = self.registry.get(record.capability_id)
        resume = getattr(module, 'resume_approval', None)
        if not manifest.supports_resume or not callable(resume) or not record.result.continuation_token:
            raise HubError(ErrorCode.TOOL_UNAVAILABLE, '此能力未提供可调用的审批恢复协议', step_id)
        # A rejected decision call must leave the saved waiting report untouched.
        try:
            returned = resume(record.result.continuation_token, decision.model_copy(deep=True))
        except ServiceError as exc:
            raise HubError(exc.code, str(exc), step_id) from exc
        except Exception as exc:
            # Unknown partial side effects cannot safely be retried automatically.
            self._fail(run, record, HubError(ErrorCode.INTERNAL_ERROR, f'恢复调用失败：{type(exc).__name__}', step_id))
            return self._drain(run)
        try:
            self._transition(run, record, StepState.WAITING_APPROVAL,
                f'收到审核：reviewer={decision.reviewer} approved={decision.approved} material_complete={decision.material_complete}')
            self._accept(run, record, returned)
        except HubError as exc:
            self._fail(run, record, exc)
        return self._drain(run)

    def _transition(self, run, record, status, message):
        record.status, record.reason = status, message
        run.events.append(TraceEvent(sequence=len(run.events)+1, ts=datetime.now(timezone.utc).isoformat(),
            trace_id=run.trace_id, task_id=run.task_id, step_id=record.step_id,
            capability_id=record.capability_id, status=status, reason=message, request_id=record.request_id,
            level='error' if record.error else 'info', error_code=record.error.code if record.error else None))

    def _fail(self, run, record, exc):
        record.error = exc.detail(run.trace_id, run.task_id, record.request_id)
        self._transition(run, record, StepState.FAILED, str(exc))

    def _accept(self, run, record, returned):
        if not isinstance(returned, AgentResult):
            raise HubError(ErrorCode.CONTRACT_MISMATCH, 'invoke/resume must return AgentResult', record.step_id)
        try:
            result = AgentResult.model_validate(returned.model_dump()).model_copy(deep=True)
        except ValidationError as exc:
            raise HubError(ErrorCode.CONTRACT_MISMATCH, str(exc), record.step_id) from exc
        record.result = result
        for name, expected in [('request_id',record.request_id), ('task_id',run.task_id),
                               ('trace_id',run.trace_id), ('capability_id',record.capability_id)]:
            if getattr(result, name) != expected:
                raise HubError(ErrorCode.CONTRACT_MISMATCH, f'Result {name} does not match request', record.step_id)
        if result.status == 'failed':
            record.error = result.error.model_copy(update={'step_id':record.step_id})
            self._transition(run, record, StepState.FAILED, record.error.message)
            return
        manifest = self.registry.get_manifest(record.capability_id)
        validate_data(result.data, manifest.output_schema, ErrorCode.CONTRACT_MISMATCH, record.step_id)
        if result.status == 'waiting_approval':
            if manifest.execution_mode != 'may_wait':
                raise HubError(ErrorCode.CONTRACT_MISMATCH, 'Immediate capability returned waiting_approval', record.step_id)
            if manifest.supports_resume != (result.continuation_token is not None):
                raise HubError(ErrorCode.CONTRACT_MISMATCH, 'Resume declaration and token disagree', record.step_id)
            self._transition(run, record, StepState.WAITING_APPROVAL, result.waiting_reason)
        else:
            record.error = None
            self._transition(run, record, StepState.COMPLETED, '能力执行完成')

    def _drain(self, run):
        for step in self.validator.topological_steps(run.plan):
            record = run.records[step.step_id]
            if record.status != StepState.PENDING:
                continue
            failed = [d for d in step.depends_on if run.records[d].status in (StepState.FAILED, StepState.SKIPPED)]
            if failed:
                record.error = HubError(ErrorCode.DEPENDENCY_FAILED, f"依赖失败：{', '.join(failed)}", step.step_id).detail(run.trace_id, run.task_id)
                self._transition(run, record, StepState.SKIPPED, record.error.message)
                continue
            blocked = [d for d in step.depends_on if run.records[d].status != StepState.COMPLETED]
            if blocked:
                self._transition(run, record, StepState.PENDING, f"等待依赖完成：{', '.join(blocked)}")
                continue
            record.request_id = f"req-{uuid4().hex[:12]}"
            self._transition(run, record, StepState.RUNNING, '解析输入并调用能力')
            try:
                payload = {}
                for key, binding in step.inputs.items():
                    if isinstance(binding, LiteralBinding):
                        payload[key] = deepcopy(binding.literal)
                    else:
                        source_id, _, *path = binding.ref.split('.')
                        value = run.records[source_id].result.data
                        for part in path:
                            if not isinstance(value, dict) or part not in value:
                                raise HubError(ErrorCode.INVALID_REFERENCE, f'Missing runtime output: {binding.ref}', step.step_id)
                            value = value[part]
                        payload[key] = deepcopy(value)
                record.inputs = deepcopy(payload)
                manifest = self.registry.get_manifest(step.capability_id)
                validate_data(payload, manifest.input_schema, ErrorCode.INVALID_INPUT, step.step_id)
                try:
                    request = AgentRequest(request_id=record.request_id, task_id=run.task_id, trace_id=run.trace_id,
                        capability_id=step.capability_id, payload=payload, context=deepcopy(run.context))
                except ValidationError as exc:
                    raise HubError(ErrorCode.INVALID_INPUT, str(exc), step.step_id) from exc
                try:
                    returned = self.registry.get(step.capability_id).invoke(request.model_copy(deep=True))
                except Exception as exc:
                    raise HubError(ErrorCode.INTERNAL_ERROR, f'{type(exc).__name__}: {exc}', step.step_id) from exc
                self._accept(run, record, returned)
            except HubError as exc:
                self._fail(run, record, exc)
        states = {record.status for record in run.records.values()}
        status = ('failed' if StepState.FAILED in states else
                  'waiting_approval' if StepState.WAITING_APPROVAL in states else 'completed')
        depended_on = {dep for s in run.plan.steps for dep in s.depends_on}
        final_results = {key: deepcopy(record.result.data) for key, record in run.records.items()
            if key not in depended_on and record.status == StepState.COMPLETED and record.result is not None}
        if StepState.WAITING_APPROVAL in states:
            self._waiting[run.task_id] = run
        else:
            self._waiting.pop(run.task_id, None)
        return ExecutionReport(plan_id=run.plan.plan_id, task_id=run.task_id, trace_id=run.trace_id,
            status=status, steps=run.records, events=run.events, final_results=final_results).model_copy(deep=True)
