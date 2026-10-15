"""ICD 1.0 candidate, pending team review. All cross-module data is JSON."""
from enum import Enum
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, model_validator
from common.errors import ErrorCode, default_retryable

Identifier = Annotated[str, Field(pattern=r"^s[1-9][0-9]*$")]
TaskId = Annotated[str, Field(pattern=r"^task-[0-9a-f]{12}$")]
RequestId = Annotated[str, Field(pattern=r"^req-[0-9a-f]{12}$")]
TraceId = Annotated[str, Field(pattern=r"^trace-[0-9a-f]{16}$")]
PlanId = Annotated[str, Field(pattern=r"^plan-[0-9]{8}-[0-9]{3}$")]
NonEmpty = Annotated[str, Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(Contract):
    code: ErrorCode
    message: NonEmpty
    retryable: bool = Field(default_factory=lambda data: default_retryable(data["code"]))
    trace_id: TraceId
    task_id: TaskId
    request_id: RequestId | None = None
    step_id: Identifier | None = None


class AgentRequest(Contract):
    request_id: RequestId
    task_id: TaskId
    trace_id: TraceId
    capability_id: NonEmpty
    payload: dict[str, JsonValue]
    context: dict[str, JsonValue] = Field(default_factory=dict)


class AgentResult(Contract):
    request_id: RequestId
    task_id: TaskId
    trace_id: TraceId
    capability_id: NonEmpty
    status: Literal["completed", "failed", "waiting_approval"]
    data: dict[str, JsonValue] = Field(default_factory=dict)
    error: ErrorDetail | None = None
    waiting_reason: str | None = None
    continuation_token: Annotated[str, Field(pattern=r"^cont-[0-9a-f]{16}$")] | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "AgentResult":
        if (self.status == "failed") != (self.error is not None):
            raise ValueError("Only failed results must carry an error")
        if self.status == "waiting_approval" and not self.waiting_reason:
            raise ValueError("Waiting results require waiting_reason")
        if self.status != "waiting_approval" and (
            self.waiting_reason is not None or self.continuation_token is not None
        ):
            raise ValueError("Waiting metadata is only valid for waiting_approval")
        if self.error and (
            self.error.trace_id != self.trace_id or self.error.task_id != self.task_id
            or self.error.request_id != self.request_id
        ):
            raise ValueError("Error correlation must match the result")
        return self


@runtime_checkable
class AgentModule(Protocol):
    """Synchronous adapter boundary. Resume is deliberately not in this protocol."""

    def invoke(self, request: AgentRequest) -> AgentResult: ...


class ApprovalDecision(Contract):
    approved: StrictBool
    reviewer: Annotated[str, Field(min_length=1, pattern=r'\S')]
    material_complete: StrictBool


@runtime_checkable
class ApprovalResumable(Protocol):
    """Optional in-process approval extension; does not invoke a new request.

    Return the original correlation IDs. Raise ServiceError on a rejected call
    without consuming the token. A returned result is the accepted continuation.
    """
    def resume_approval(self, continuation_token: str, decision: ApprovalDecision) -> AgentResult: ...


class CapabilityManifest(Contract):
    capability_id: NonEmpty
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+$")]
    name: NonEmpty
    description: NonEmpty
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    preconditions: list[str]
    side_effects: Literal["read_only", "writes_mock_state", "requires_approval"]
    execution_mode: Literal["immediate", "may_wait"]
    supports_resume: bool = False
    owner: NonEmpty


class LiteralBinding(Contract):
    literal: JsonValue


class ReferenceBinding(Contract):
    ref: Annotated[str, Field(pattern=r"^s[1-9][0-9]*\.data(?:\.[A-Za-z0-9_-]+)*$")]


class ExecutionStep(Contract):
    step_id: Identifier
    capability_id: NonEmpty
    depends_on: list[Identifier] = Field(default_factory=list)
    inputs: dict[str, LiteralBinding | ReferenceBinding] = Field(default_factory=dict)


class ExecutionPlan(Contract):
    plan_id: PlanId
    goal: NonEmpty
    steps: list[ExecutionStep] = Field(min_length=1)


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"
    SKIPPED = "skipped"


class StepRecord(Contract):
    step_id: Identifier
    capability_id: str
    depends_on: list[Identifier]
    request_id: RequestId | None = None
    status: StepState = StepState.PENDING
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    result: AgentResult | None = None
    error: ErrorDetail | None = None
    reason: str | None = None


class TraceEvent(Contract):
    sequence: int
    ts: str
    level: Literal["info", "error"]
    trace_id: TraceId
    task_id: TaskId
    request_id: RequestId | None = None
    step_id: Identifier
    capability_id: str
    status: StepState
    reason: str
    error_code: ErrorCode | None = None


class ExecutionReport(Contract):
    plan_id: PlanId
    task_id: TaskId
    trace_id: TraceId
    status: Literal["completed", "failed", "waiting_approval"]
    steps: dict[str, StepRecord]
    events: list[TraceEvent]
    final_results: dict[str, dict[str, JsonValue]]
