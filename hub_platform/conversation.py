"""In-process top-level context and natural-language task execution.

Conversation history stays here. Modules only receive explicit business inputs and
session_id metadata. No database, implicit resume or second answer-generation LLM.
"""
from typing import Literal
from uuid import uuid4

from pydantic import Field

from common.contracts import Contract, ErrorDetail, ExecutionPlan, ExecutionReport, StepState
from common.errors import ErrorCode
from hub_platform.errors import HubError
from hub_platform.executor import Executor
from hub_platform.planner import DynamicPlanner, PlanningAttempt, PlanningError


class Message(Contract):
    role: Literal['user', 'assistant']
    content: str


class TaskContext(Contract):
    task_id: str = Field(default_factory=lambda: f'task-{uuid4().hex[:12]}')
    trace_id: str = Field(default_factory=lambda: f'trace-{uuid4().hex[:16]}')
    messages: list[Message] = Field(default_factory=list)
    plan: ExecutionPlan | None = None
    report: ExecutionReport | None = None
    status: str = 'new'

    @property
    def goal(self):
        return '\n补充：'.join(item.content for item in self.messages if item.role == 'user')


class SessionContext(Contract):
    session_id: str = Field(default_factory=lambda: f'sess-{uuid4().hex[:12]}')
    active_task: TaskContext | None = None
    history: list[TaskContext] = Field(default_factory=list)


class TurnResult(Contract):
    session_id: str
    task_id: str
    trace_id: str
    status: Literal['ready', 'needs_clarification', 'unsupported', 'completed', 'failed', 'waiting_approval']
    message: str
    plan: ExecutionPlan | None = None
    report: ExecutionReport | None = None
    error: ErrorDetail | None = None
    planning_attempts: list[PlanningAttempt] = Field(default_factory=list)


class Conversation:
    def __init__(self, planner: DynamicPlanner):
        self.planner = planner
        self.executor = Executor(planner.registry, planner.validator.max_steps)
        self._context = SessionContext()

    @property
    def context(self) -> SessionContext:
        return self._context.model_copy(deep=True)

    def new_task(self):
        """Explicitly leave the current task; keep its report as history, never resume it."""
        if self._context.active_task is not None:
            self._context.history.append(self._context.active_task.model_copy(deep=True))
        self._context.active_task = None

    def reset(self):
        self._context = SessionContext()

    def submit(self, text: str, *, execute: bool = True) -> TurnResult:
        task = self._context.active_task
        if task and task.report and any(
            step.status == StepState.WAITING_APPROVAL for step in task.report.steps.values()
        ):
            # Aggregate failure must not hide a pending approval in another branch.
            # The executor has no resume protocol: preserve the report, never replay it.
            message = ('此任务包含失败步骤，仍有步骤等待审批；' if task.report.status == 'failed'
                       else '此任务仍在等待审批；')
            return TurnResult(session_id=self._context.session_id, task_id=task.task_id,
                              trace_id=task.trace_id, status=task.report.status,
                              message=message + '当前版本不支持恢复。可用 /new 开始另一项任务。',
                              plan=task.plan.model_copy(deep=True), report=task.report.model_copy(deep=True))
        if task and task.status in ('completed', 'unsupported', 'execution_failed'):
            self.new_task()
            task = None
        if task is None:
            task = TaskContext()
            self._context.active_task = task
        ids = {'session_id': self._context.session_id, 'task_id': task.task_id, 'trace_id': task.trace_id}
        if not isinstance(text, str) or not text.strip():
            return TurnResult(**ids, status='failed', message='请输入任务目标。', error=ErrorDetail(
                code=ErrorCode.INVALID_INPUT, message='请输入任务目标。', task_id=task.task_id, trace_id=task.trace_id))
        task.messages.append(Message(role='user', content=text.strip()))
        context = {'session_id': self._context.session_id,
                   'active_task': task.model_dump(mode='json'),
                   'history': [item.model_dump(mode='json') for item in self._context.history]}
        try:
            planned = self.planner.plan(task.goal, context=context)
        except PlanningError as exc:
            task.status = 'planning_failed'
            task.messages.append(Message(role='assistant', content=f'计划生成失败：{exc}'))
            return TurnResult(**ids, status='failed', message=f'计划生成失败：{exc}',
                              error=ErrorDetail(code=exc.code, message=str(exc), retryable=exc.retryable,
                                                task_id=task.task_id, trace_id=task.trace_id),
                              planning_attempts=exc.attempts)
        task.status = planned.decision.status
        task.plan = planned.plan.model_copy(deep=True) if planned.plan else None
        task.messages.append(Message(role='assistant', content=planned.decision.message))
        if task.plan is None or not execute:
            return TurnResult(**ids, status=planned.decision.status, message=planned.decision.message,
                              plan=task.plan.model_copy(deep=True) if task.plan else None,
                              planning_attempts=planned.attempts)
        try:
            report = self.executor.execute(task.plan, task_id=task.task_id, trace_id=task.trace_id,
                                           context={'session_id': self._context.session_id})
        except HubError as exc:
            task.status = 'planning_failed'
            return TurnResult(**ids, status='failed', message=str(exc), plan=task.plan.model_copy(deep=True),
                              error=exc.detail(task.trace_id, task.task_id), planning_attempts=planned.attempts)
        task.report = report.model_copy(deep=True)
        task.status = 'execution_failed' if report.status == 'failed' else report.status
        message = {'completed': '执行完成，结果见各步骤与最终输出。',
                   'failed': '执行失败，保留已完成步骤和错误来源。',
                   'waiting_approval': '任务等待人工审批，依赖步骤已挂起。'}[report.status]
        task.messages.append(Message(role='assistant', content=message))
        return TurnResult(**ids, status=report.status, message=message, plan=task.plan.model_copy(deep=True),
                          report=report, planning_attempts=planned.attempts)
