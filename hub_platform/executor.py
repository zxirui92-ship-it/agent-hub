from common.errors import ErrorCode
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from common.contracts import (
    AgentRequest, AgentResult, ExecutionPlan, ExecutionReport, LiteralBinding,
    StepRecord, StepState, TraceEvent,
)
from hub_platform.errors import HubError
from hub_platform.registry import CapabilityRegistry
from hub_platform.schema import validate_data
from hub_platform.validator import PlanValidator


class Executor:
    def __init__(self, registry: CapabilityRegistry, max_steps: int = 32) -> None:
        self.registry = registry
        self.validator = PlanValidator(registry, max_steps)

    def execute(self, raw: ExecutionPlan | dict[str, Any], *, task_id: str | None = None,
                trace_id: str | None = None, context: dict[str, Any] | None = None) -> ExecutionReport:
        """One fresh in-memory run. This method never resumes or retries a prior run."""
        plan = self.validator.validate(raw)
        task_id, trace_id = task_id or f"task-{uuid4().hex[:12]}", trace_id or f"trace-{uuid4().hex[:16]}"
        records = {step.step_id: StepRecord(step_id=step.step_id, capability_id=step.capability_id,
                                          depends_on=step.depends_on) for step in plan.steps}
        events: list[TraceEvent] = []

        def transition(record: StepRecord, status: StepState, message: str) -> None:
            record.status = status
            events.append(TraceEvent(sequence=len(events) + 1, ts=datetime.now(timezone.utc).isoformat(),
                          trace_id=trace_id, task_id=task_id, step_id=record.step_id,
                          capability_id=record.capability_id, status=status, reason=message, request_id=record.request_id,
                          level="error" if record.error else "info",
                          error_code=record.error.code if record.error else None))

        for record in records.values():
            transition(record, StepState.PENDING, "已加入执行计划")

        for step in self.validator.topological_steps(plan):
            record = records[step.step_id]
            failed = [dep for dep in step.depends_on
                      if records[dep].status in (StepState.FAILED, StepState.SKIPPED)]
            if failed:
                record.error = HubError(ErrorCode.DEPENDENCY_FAILED, f"依赖失败：{', '.join(failed)}",
                                        step.step_id).detail(trace_id, task_id)
                record.reason = record.error.message
                transition(record, StepState.SKIPPED, record.reason)
                continue
            blocked = [dep for dep in step.depends_on if records[dep].status != StepState.COMPLETED]
            if blocked:
                record.reason = f"等待依赖完成：{', '.join(blocked)}"
                transition(record, StepState.PENDING, record.reason)
                continue
            record.request_id = f"req-{uuid4().hex[:12]}"
            transition(record, StepState.RUNNING, "解析输入并调用能力")
            try:
                payload: dict[str, Any] = {}
                for key, binding in step.inputs.items():
                    if isinstance(binding, LiteralBinding):
                        payload[key] = deepcopy(binding.literal)
                    else:
                        source_id, _, *path = binding.ref.split(".")
                        source_result = records[source_id].result
                        assert source_result is not None  # Completed dependency has a result.
                        value: Any = source_result.data
                        for part in path:
                            if not isinstance(value, dict) or part not in value:
                                raise HubError(ErrorCode.INVALID_REFERENCE, f"Missing runtime output: {binding.ref}", step.step_id)
                            value = value[part]
                        payload[key] = deepcopy(value)
                record.inputs = deepcopy(payload)
                manifest = self.registry.get_manifest(step.capability_id)
                validate_data(payload, manifest.input_schema, ErrorCode.INVALID_INPUT, step.step_id)
                try:
                    request = AgentRequest(request_id=record.request_id, task_id=task_id, trace_id=trace_id,
                                           capability_id=step.capability_id, payload=payload,
                                           context=deepcopy(context or {}))
                except ValidationError as exc:
                    raise HubError(ErrorCode.INVALID_INPUT, str(exc), step.step_id) from exc
                # Catch unknown exceptions only at the external adapter boundary.
                # Preserve the failure type/message in the report; never invent success.
                try:
                    returned = self.registry.get(step.capability_id).invoke(request.model_copy(deep=True))
                except Exception as exc:
                    raise HubError(ErrorCode.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}", step.step_id) from exc
                if not isinstance(returned, AgentResult):
                    raise HubError(ErrorCode.CONTRACT_MISMATCH, "invoke must return AgentResult", step.step_id)
                try:
                    result = AgentResult.model_validate(returned.model_dump()).model_copy(deep=True)
                except ValidationError as exc:
                    raise HubError(ErrorCode.CONTRACT_MISMATCH, str(exc), step.step_id) from exc
                record.result = result
                for field in ("request_id", "task_id", "trace_id", "capability_id"):
                    if getattr(result, field) != getattr(request, field):
                        raise HubError(ErrorCode.CONTRACT_MISMATCH, f"Result {field} does not match request", step.step_id)
                if result.status == "failed":
                    record.error = result.error.model_copy(update={"step_id": step.step_id})
                    record.reason = record.error.message
                    transition(record, StepState.FAILED, record.reason)
                    continue
                validate_data(result.data, manifest.output_schema, ErrorCode.CONTRACT_MISMATCH, step.step_id)
                if result.status == "waiting_approval":
                    if manifest.execution_mode != "may_wait":
                        raise HubError(ErrorCode.CONTRACT_MISMATCH, "Immediate capability returned waiting_approval", step.step_id)
                    if manifest.supports_resume != (result.continuation_token is not None):
                        raise HubError(ErrorCode.CONTRACT_MISMATCH, "Resume declaration and token disagree", step.step_id)
                    record.reason = result.waiting_reason
                    transition(record, StepState.WAITING_APPROVAL, record.reason)
                else:
                    transition(record, StepState.COMPLETED, "能力执行完成")
            except HubError as exc:
                record.error = exc.detail(trace_id, task_id, record.request_id)
                record.reason = str(exc)
                transition(record, StepState.FAILED, record.reason)

        states = {record.status for record in records.values()}
        status = ("failed" if StepState.FAILED in states else
                  "waiting_approval" if StepState.WAITING_APPROVAL in states else "completed")
        depended_on = {dep for step in plan.steps for dep in step.depends_on}
        final_results = {key: deepcopy(record.result.data) for key, record in records.items()
                         if key not in depended_on and record.status == StepState.COMPLETED
                         and record.result is not None}
        return ExecutionReport(plan_id=plan.plan_id, task_id=task_id, trace_id=trace_id,
                               status=status, steps=records, events=events, final_results=final_results)
