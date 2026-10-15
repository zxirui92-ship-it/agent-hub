"""Minimal chat-completions adapter shared by the Planner and model-using modules."""
from typing import Protocol

from common.errors import ErrorCode, ServiceError
from common.http_client import post_json
from common.json_data import strict_json_loads


class TextModel(Protocol):
    def complete(self, system: str, query: str) -> str: ...


class ChatModel:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30, transport=post_json):
        self.base_url, self.api_key, self.model = base_url, api_key, model
        self.timeout, self.transport = timeout, transport

    def complete(self, system: str, query: str) -> str:
        if not all((self.base_url, self.api_key, self.model)):
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'LLM service not_configured: set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL', retryable=False)
        response = self.transport(self.base_url.rstrip('/') + '/chat/completions',
            {'model': self.model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': query}]},
            self.api_key, self.timeout)
        try:
            text = response['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError) as exc:
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'LLM response missing choices[0].message.content') from exc
        if not isinstance(text, str) or not text.strip():
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'LLM response content must be nonempty text')
        return text


def json_object(text: str) -> dict:
    try:
        value = strict_json_loads(text)
    except (ValueError, TypeError) as exc:
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Model must return a JSON object without Markdown fences') from exc
    if not isinstance(value, dict):
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Model output must be a JSON object')
    return value
