"""Image generations endpoint. Return supplied URL/base64; never invent an asset path."""
import base64
import binascii
import json
from urllib.parse import urlparse

from agents.router.skills import query_text
from common.errors import ErrorCode, ServiceError
from common.http_client import post_json

# Real bytes of a one-pixel PNG, only for the explicitly labeled offline path.
MOCK_PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII='


class ImageGenSkill:
    def __init__(self, base_url='', api_key='', model='', timeout=60, *, mock=False, transport=post_json):
        self.base_url, self.api_key, self.model = base_url, api_key, model
        self.timeout, self.mock, self.transport = timeout, mock, transport

    def run(self, payload: dict) -> str:
        query = query_text(payload)
        if self.mock:
            return json.dumps({'mode': 'mock', 'images': [{'image_base64': MOCK_PNG}],
                               'description': 'One-pixel PNG test resource; no image model called'})
        if not all((self.base_url, self.api_key, self.model)):
            raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'Image service not_configured: set M4_IMAGE_BASE_URL, M4_IMAGE_API_KEY and M4_IMAGE_MODEL', retryable=False)
        value = self.transport(self.base_url.rstrip('/') + '/images/generations',
            {'model': self.model, 'prompt': query, 'n': 1}, self.api_key, self.timeout)
        rows = value.get('data')
        if not isinstance(rows, list) or not rows:
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Image response missing nonempty data array')
        images = []
        for row in rows:
            if not isinstance(row, dict):
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Invalid image object')
            if isinstance(row.get('b64_json'), str) and row['b64_json']:
                try:
                    if not base64.b64decode(row['b64_json'], validate=True):
                        raise ValueError('Empty image')
                except (ValueError, binascii.Error) as exc:
                    raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Invalid image base64 data') from exc
                images.append({'image_base64': row['b64_json']})
            elif isinstance(row.get('url'), str) and urlparse(row['url']).scheme in ('https', 'http') and urlparse(row['url']).netloc:
                images.append({'image_url': row['url']})
            else:
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Image response has no valid URL or base64 data')
        return json.dumps({'mode': 'live', 'images': images}, ensure_ascii=False)
