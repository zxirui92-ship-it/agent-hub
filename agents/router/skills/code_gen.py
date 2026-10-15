"""Generate code text through the shared model adapter; never execute it."""
import json

from agents.router.skills import query_text
from common.errors import ErrorCode, ServiceError
from common.llm import TextModel
from agents.router.structured import request_object


class CodeGenSkill:
    def __init__(self, model: TextModel | None = None, *, mock=False):
        self.model, self.mock = model, mock

    def run(self, payload: dict) -> str:
        query = query_text(payload)
        if self.mock:
            return json.dumps({'mode': 'mock', 'language': 'python',
                               'code': '# Offline test sample, not model-generated for this request.\nprint("mock")\n'}, ensure_ascii=False)
        if self.model is None:
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'Code generation service not_configured', retryable=False)
        def validate(value):
            if set(value) != {'language', 'code'} or not all(isinstance(value[k], str) and value[k].strip() for k in value):
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Generated code requires exactly language and code, both nonempty strings')
        value = request_object(self.model,
            'Generate code according to the user request. Return only JSON with exactly language and code, '
            'both nonempty strings. Escape newlines inside the code JSON string. '
            'Explain the language using its conventional name. Do not execute code.', query, validate, stage='代码生成')
        return json.dumps({'mode': 'live', **value}, ensure_ascii=False)
