from common.contracts import ErrorDetail
from common.errors import ErrorCode


class HubError(Exception):
    def __init__(self, code: ErrorCode, message: str, step_id: str | None = None):
        super().__init__(message)
        self.code = ErrorCode(code)
        self.step_id = step_id

    def detail(self, trace_id: str, task_id: str, request_id: str | None = None) -> ErrorDetail:
        return ErrorDetail(code=self.code, message=str(self), trace_id=trace_id,
                           task_id=task_id, request_id=request_id, step_id=self.step_id)
