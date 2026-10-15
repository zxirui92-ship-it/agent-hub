"""Minimal chat-completions adapter shared by the Planner and model-using modules."""
from typing import Protocol
import re

from common.errors import ErrorCode, ServiceError
from common.http_client import post_json
from common.json_data import strict_json_loads


class TextModel(Protocol):
    def complete(self, system: str, query: str) -> str: ...


class ChatModel:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30, transport=post_json, *, json_mode=False):
        self.base_url, self.api_key, self.model = base_url, api_key, model
        self.timeout, self.transport = timeout, transport
        self.json_mode = json_mode

    def complete(self, system: str, query: str) -> str:
        if not all((self.base_url, self.api_key, self.model)):
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'LLM service not_configured: set LLM_BASE_URL, LLM_API_KEY and LLM_MODEL', retryable=False)
        payload = {'model': self.model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': query}]}
        if self.json_mode:
            payload['response_format'] = {'type': 'json_object'}
        response = self.transport(self.base_url.rstrip('/') + '/chat/completions', payload, self.api_key, self.timeout)
        try:
            text = response['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError) as exc:
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'LLM response missing choices[0].message.content') from exc
        if not isinstance(text, str) or not text.strip():
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'LLM response content must be nonempty text')
        return text


def json_object(text: str, *, allow_fence: bool = False) -> dict:
    # Some compatible providers wrap otherwise valid JSON. Accept exactly one
    # complete JSON fence only when the caller opts in; never extract a substring
    # from prose, repair broken JSON, or discard trailing output.
    if allow_fence and isinstance(text, str):
        match = re.fullmatch(r'\s*```(?:json)?[ \t]*\r?\n(.*?)\r?\n```\s*', text, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1)
    try:
        value = strict_json_loads(text)
    except (ValueError, TypeError) as exc:
        if allow_fence:
            location = f'（第 {exc.lineno} 行，第 {exc.colno} 列）' if hasattr(exc, 'lineno') else ''
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, f'模型响应不是完整有效的 JSON 对象{location}') from exc
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Model must return a JSON object without Markdown fences') from exc
    if not isinstance(value, dict):
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Model output must be a JSON object')
    return value
