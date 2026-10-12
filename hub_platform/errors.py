from common.contracts import ErrorDetail


class HubError(Exception):
    def __init__(self, code: str, message: str, step_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.step_id = step_id

    def detail(self, trace_id: str, task_id: str) -> ErrorDetail:
        return ErrorDetail(code=self.code, message=str(self), trace_id=trace_id,
                           task_id=task_id, step_id=self.step_id)
