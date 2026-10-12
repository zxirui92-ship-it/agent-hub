"""Shared, explicit error vocabulary. Retryability is metadata, not a retry policy."""
from enum import Enum


class ErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
    EXECUTION_LIMIT = "EXECUTION_LIMIT"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
    DUPLICATE_CAPABILITY = "DUPLICATE_CAPABILITY"
    INVALID_PLAN = "INVALID_PLAN"
    INVALID_PLAN_FILE = "INVALID_PLAN_FILE"
    DUPLICATE_STEP = "DUPLICATE_STEP"
    INVALID_DEPENDENCY = "INVALID_DEPENDENCY"
    CYCLIC_DEPENDENCY = "CYCLIC_DEPENDENCY"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    INVALID_REFERENCE = "INVALID_REFERENCE"


def default_retryable(code: ErrorCode) -> bool:
    return code in (ErrorCode.TOOL_UNAVAILABLE, ErrorCode.INTERNAL_ERROR)


class ServiceError(Exception):
    """Public diagnostic raised by model/tool adapters; never includes raw HTTP bodies."""
    def __init__(self, code: ErrorCode, message: str, *, retryable: bool | None = None):
        super().__init__(message)
        self.code = code
        self.retryable = default_retryable(code) if retryable is None else retryable
