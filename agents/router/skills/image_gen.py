"""Image generations endpoint. Return supplied URL/base64; never invent an asset path."""
import base64
import binascii
import json

from agents.router.skills import query_text
from common.errors import ErrorCode, ServiceError
from common.http_client import parse_http_url, post_json

# Real bytes of a one-pixel PNG, only for the explicitly labeled offline path.
MOCK_PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII='


def _has_raster_signature(raw: bytes) -> bool:
    """Check PNG/JPEG/WebP signatures and framing, without decoding pixels.

    These are the generated-image formats supported by this adapter. This is a
    media-type boundary, not a full image decoder or a safety verdict on pixels.
    """
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        if (len(raw) < 57 or raw[8:16] != b'\x00\x00\x00\rIHDR'
                or not int.from_bytes(raw[16:20], 'big') or not int.from_bytes(raw[20:24], 'big')):
            return False
        offset, has_data = 8, False
        while offset + 12 <= len(raw):
            size = int.from_bytes(raw[offset:offset + 4], 'big')
            end = offset + size + 12
            if end > len(raw):
                return False
            kind = raw[offset + 4:offset + 8]
            if binascii.crc32(raw[offset + 4:end - 4]) != int.from_bytes(raw[end - 4:end], 'big'):
                return False
            if kind == b'IDAT':
                has_data = has_data or size > 0
            elif kind == b'IEND':
                return has_data and size == 0 and end == len(raw)
            offset = end
        return False
    if raw.startswith(b'\xff\xd8\xff') and raw.endswith(b'\xff\xd9'):
        offset, has_frame = 2, False
        while offset + 4 <= len(raw):
            if raw[offset] != 0xff:
                return False
            while offset < len(raw) and raw[offset] == 0xff:
                offset += 1
            if offset + 3 > len(raw):
                return False
            marker = raw[offset]
            size = int.from_bytes(raw[offset + 1:offset + 3], 'big')
            end = offset + 1 + size
            if size < 2 or end > len(raw) - 2:
                return False
            # Baseline, extended sequential, and progressive JPEG frames.
            if marker in (0xc0, 0xc1, 0xc2):
                if size < 8 or not int.from_bytes(raw[offset + 4:offset + 6], 'big') or not int.from_bytes(raw[offset + 6:offset + 8], 'big'):
                    return False
                has_frame = True
            elif marker == 0xda:
                return has_frame and size >= 6 and end < len(raw) - 2
            offset = end
        return False
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        if len(raw) < 26 or int.from_bytes(raw[4:8], 'little') + 8 != len(raw):
            return False
        offset, has_frame = 12, False
        while offset + 8 <= len(raw):
            kind = raw[offset:offset + 4]
            size = int.from_bytes(raw[offset + 4:offset + 8], 'little')
            start, end = offset + 8, offset + 8 + size
            if end + (size % 2) > len(raw):
                return False
            if kind == b'VP8 ':
                if (size < 10 or raw[start] & 1 or raw[start + 3:start + 6] != b'\x9d\x01\x2a'
                        or not int.from_bytes(raw[start + 6:start + 8], 'little') & 0x3fff
                        or not int.from_bytes(raw[start + 8:start + 10], 'little') & 0x3fff):
                    return False
                has_frame = True
            elif kind == b'VP8L':
                if size < 5 or raw[start] != 0x2f or raw[start + 4] >> 5:
                    return False
                has_frame = True
            elif kind == b'VP8X' and size != 10:
                return False
            offset = end + (size % 2)
        return has_frame and offset == len(raw)
    return False


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
                    raw = base64.b64decode(row['b64_json'], validate=True)
                    if not _has_raster_signature(raw):
                        raise ValueError('Unsupported or invalid image bytes')
                except (ValueError, binascii.Error) as exc:
                    raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Invalid image base64 data; expected PNG, JPEG or WebP') from exc
                images.append({'image_base64': row['b64_json']})
            elif isinstance(row.get('url'), str):
                try:
                    parse_http_url(row['url'])
                except ValueError as exc:
                    raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Image response has no valid URL or base64 data') from exc
                images.append({'image_url': row['url']})
            else:
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Image response has no valid URL or base64 data')
        return json.dumps({'mode': 'live', 'images': images}, ensure_ascii=False)
