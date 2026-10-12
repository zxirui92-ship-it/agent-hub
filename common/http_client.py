"""Small synchronous JSON transport. One attempt, finite timeout, no SDK objects."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from common.errors import ErrorCode, ServiceError


def post_json(url: str, payload: dict, api_key: str, timeout: float) -> dict:
    request = Request(url, data=json.dumps(payload).encode('utf-8'), method='POST',
                      headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'})
    try:
        with urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read())
    except HTTPError as exc:
        raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, f'External service HTTP {exc.code}',
                           retryable=exc.code in (408, 429) or exc.code >= 500) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, f'External service connection failed ({type(exc).__name__})') from exc
    except (ValueError, UnicodeError) as exc:
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'External service returned invalid JSON') from exc
    if not isinstance(value, dict):
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'External service response must be an object')
    return value
