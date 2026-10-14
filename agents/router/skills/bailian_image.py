"""Qwen-Image synchronous native API; no task polling or invented resources."""
import json
from urllib.parse import urlsplit, urlunsplit
from common.errors import ErrorCode, ServiceError
from common.http_client import post_json
from agents.router.skills import query_text
from agents.router.skills.image_gen import ImageGenSkill


def generation_url(base_url):
    parts = urlsplit(base_url)
    path = parts.path.rstrip('/')
    endpoint = '/api/v1/services/aigc/multimodal-generation/generation'
    if (parts.scheme not in ('https', 'http') or not parts.netloc or parts.query or parts.fragment
            or parts.username or parts.password or path not in ('', '/compatible-mode/v1', '/api/v1', endpoint)):
        raise ValueError('Bailian base URL must be an origin, compatible-mode/v1, api/v1 or the native image endpoint')
    return urlunsplit((parts.scheme, parts.netloc, endpoint, '', ''))


class BailianImageSkill:
    def __init__(self, base_url='', api_key='', model='qwen-image-2.0', timeout=180, *, mock=False, transport=post_json):
        self.base_url, self.api_key, self.model = base_url, api_key, model
        self.timeout, self.mock, self.transport = timeout, mock, transport

    def run(self, payload: dict) -> str:
        query = query_text(payload)
        if self.mock:
            return ImageGenSkill(mock=True).run(payload)
        if not all((self.base_url, self.api_key, self.model)):
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE,
                'Bailian image service not_configured: set BAILIAN_BASE_URL and BAILIAN_API_KEY', retryable=False)
        try:
            url = generation_url(self.base_url)
        except ValueError as exc:
            raise ServiceError(ErrorCode.INVALID_INPUT, str(exc), retryable=False) from exc
        response = self.transport(url, {'model': self.model,
            'input': {'messages': [{'role': 'user', 'content': [{'text': query}]}]},
            'parameters': {'n': 1, 'size': '1024*1024', 'prompt_extend': False}}, self.api_key, self.timeout)
        if response.get('code'):
            # Provider body is not a public diagnostic: it may echo private input.
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'Bailian image service returned a provider error', retryable=False)
        try:
            choices = response['output']['choices']
            if not isinstance(choices, list) or not choices:
                raise ValueError('No image choices')
            images = []
            for choice in choices:
                content = choice['message']['content']
                if not isinstance(content, list):
                    raise ValueError('Invalid content')
                for item in content:
                    resource = item.get('image')
                    if resource is None:
                        continue
                    if not isinstance(resource, str):
                        raise ValueError('Invalid image URL')
                    parsed = urlsplit(resource)
                    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
                        raise ValueError('Invalid image URL')
                    images.append({'image_url': resource})
            if not images:
                raise ValueError('No images')
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Bailian response missing valid output image URLs', retryable=False) from exc
        return json.dumps({'mode': 'live', 'provider': 'bailian', 'model': self.model, 'images': images})
