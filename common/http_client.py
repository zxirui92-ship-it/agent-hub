"""Small synchronous JSON transport. One attempt, finite timeout, no SDK objects."""
import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from common.errors import ErrorCode, ServiceError
from common.json_data import strict_json_loads


def parse_http_url(url: str):
    """Validate an HTTP resource without accepting credentials or parser repairs."""
    if not isinstance(url, str) or not url or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError('Invalid HTTP URL')
    parts = urlsplit(url)
    if (parts.scheme not in ('http', 'https') or not parts.hostname
            or parts.username is not None or parts.password is not None
            or '\\' in parts.netloc or parts.netloc.endswith(':')):
        raise ValueError('Invalid HTTP URL')
    # Accessing port also validates non-numeric and out-of-range ports.
    if parts.port is not None and parts.port < 1:
        raise ValueError('Invalid HTTP URL')
    if parts.netloc.startswith('['):
        suffix = parts.netloc.partition(']')[2]
        if suffix and not suffix.startswith(':'):
            raise ValueError('Invalid HTTP URL')
    return parts


def _origin(url: str):
    parts = parse_http_url(url)
    return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80)


class SameOriginRedirectHandler(HTTPRedirectHandler):
    """Keep credentials on their original origin; never follow HTTPS downgrades."""

    @staticmethod
    def _validate_redirect(req, fp, code, headers, newurl):
        try:
            if _origin(req.full_url) != _origin(newurl):
                raise ValueError('Cross-origin redirect')
        except ValueError:
            raise HTTPError(req.full_url, code, 'Unsafe external service redirect rejected', headers, fp) from None

    def http_error_302(self, req, fp, code, msg, headers):
        # Validate before urllib parses/normalizes Location, including malformed
        # IPv6 and control characters that urlsplit would otherwise strip.
        location = headers.get('location', headers.get('uri'))
        if location is not None:
            try:
                if any(ord(char) <= 32 or ord(char) == 127 for char in location):
                    raise ValueError('Invalid redirect URL')
                target = urljoin(req.full_url, location)
            except ValueError:
                raise HTTPError(req.full_url, code, 'Invalid external service redirect', headers, fp) from None
            self._validate_redirect(req, fp, code, headers, target)
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._validate_redirect(req, fp, code, headers, newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urlopen(request, *, timeout):
    # Do not install a process-global opener or inherit an unsafe default
    # redirect policy. Other callers of urllib remain unaffected.
    return build_opener(SameOriginRedirectHandler()).open(request, timeout=timeout)


def post_json(url: str, payload: dict, api_key: str, timeout: float) -> dict:
    try:
        parse_http_url(url)
    except ValueError as exc:
        raise ServiceError(ErrorCode.INVALID_INPUT, 'External service URL must be a valid HTTP(S) URL without credentials') from exc
    try:
        data = json.dumps(payload, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ServiceError(ErrorCode.INVALID_INPUT, 'External service payload must be valid JSON with finite numbers') from exc
    request = Request(url, data=data, method='POST',
                      headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'})
    try:
        with urlopen(request, timeout=timeout) as response:
            value = strict_json_loads(response.read())
    except HTTPError as exc:
        raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, f'External service HTTP {exc.code}',
                           retryable=exc.code in (408, 429) or exc.code >= 500) from exc
    except (HTTPException, URLError, TimeoutError, OSError) as exc:
        raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, f'External service connection failed ({type(exc).__name__})', retryable=True) from exc
    except (ValueError, UnicodeError) as exc:
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'External service returned invalid JSON') from exc
    if not isinstance(value, dict):
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'External service response must be an object')
    return value
