"""ICD 0.1 candidate, pending team review. All cross-module data is JSON."""
from enum import Enum
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Identifier = Annotated[str, Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")]
NonEmpty = Annotated[str, Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(Contract):
    code: NonEmpty
    message: NonEmpty
    trace_id: NonEmpty
    task_id: NonEmpty
    step_id: str | None = None


class AgentRequest(Contract):
    request_id: NonEmpty
    task_id: NonEmpty
    trace_id: NonEmpty
    capability_id: NonEmpty
    payload: dict[str, JsonValue]
    context: dict[str, JsonValue] = Field(default_factory=dict)


class AgentResult(Contract):
    request_id: NonEmpty
    task_id: NonEmpty
    trace_id: NonEmpty
    capability_id: NonEmpty
    status: Literal["completed", "failed", "waiting_approval"]
    data: dict[str, JsonValue] = Field(default_factory=dict)
    error: ErrorDetail | None = None
    waiting_reason: str | None = None
    continuation_token: str | None = None

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
        ):
            raise ValueError("Error correlation must match the result")
        return self


@runtime_checkable
class AgentModule(Protocol):
    """Synchronous adapter boundary. Resume is deliberately not in this protocol."""

    def invoke(self, request: AgentRequest) -> AgentResult: ...


class CapabilityManifest(Contract):
    capability_id: NonEmpty
    version: NonEmpty
    name: NonEmpty
    description: NonEmpty
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    preconditions: list[str]
    side_effects: Literal["read_only", "simulated_write", "requires_approval"]
    execution_mode: Literal["immediate", "may_wait"]
    supports_resume: bool = False
    owner: NonEmpty


class LiteralBinding(Contract):
    literal: JsonValue


class ReferenceBinding(Contract):
    ref: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+\.data(?:\.[A-Za-z0-9_-]+)*$")]


class ExecutionStep(Contract):
    step_id: Identifier
    capability_id: NonEmpty
    depends_on: list[Identifier] = Field(default_factory=list)
    inputs: dict[str, LiteralBinding | ReferenceBinding] = Field(default_factory=dict)


class ExecutionPlan(Contract):
    plan_id: NonEmpty
    goal: NonEmpty
    steps: list[ExecutionStep] = Field(min_length=1)


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"
    SKIPPED = "skipped"


class StepRecord(Contract):
    step_id: str
    capability_id: str
    depends_on: list[str]
    status: StepStatus = StepStatus.PENDING
    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    result: AgentResult | None = None
    error: ErrorDetail | None = None
    reason: str | None = None


class TraceEvent(Contract):
    sequence: int
    timestamp: str
    trace_id: str
    task_id: str
    step_id: str
    capability_id: str
    status: StepStatus
    message: str
    error_code: str | None = None


class ExecutionReport(Contract):
    plan_id: str
    task_id: str
    trace_id: str
    status: Literal["completed", "failed", "waiting_approval"]
    steps: dict[str, StepRecord]
    events: list[TraceEvent]
    final_results: dict[str, dict[str, JsonValue]]
