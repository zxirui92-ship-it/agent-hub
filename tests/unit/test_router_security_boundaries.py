"""Offline regressions for the production HTTP and generated-media boundaries."""
import base64
from email.message import Message
from http.client import BadStatusLine, HTTPException, IncompleteRead, RemoteDisconnected
from io import BytesIO
import json
from urllib.request import BaseHandler, ProxyHandler, build_opener
from urllib.response import addinfourl

import pytest

from agents.router.skills.bailian_image import BailianImageSkill
from agents.router.skills.image_gen import ImageGenSkill, MOCK_PNG
from agents.router.skills.web_search import WebSearchSkill
from common import http_client
from common.errors import ErrorCode, ServiceError


KEY = 'SYNTHETIC-BOUNDARY-TEST-KEY'
# One-pixel fixtures generated once with Pillow; Pillow is not a test/runtime dependency.
JPEG = (
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIs'
    'IxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy'
    'MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAA'
    'AAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAk'
    'M2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKT'
    'lJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QA'
    'HwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdh'
    'cRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hp'
    'anN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk'
    '5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iiigD//2Q=='
)
WEBP = 'UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAUAmJaQAA3AA/vz0AAA='
WEBP_LOSSLESS = 'UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA='


class MemoryHttpHandler(BaseHandler):
    handler_order = 100

    def __init__(self, redirects):
        self.redirects = redirects
        self.calls = []

    def https_open(self, request):
        self.calls.append((request.full_url, request.get_method(), request.get_header('Authorization')))
        headers = Message()
        if len(self.calls) <= len(self.redirects):
            status, location = self.redirects[len(self.calls) - 1]
            headers['Location'] = location
            body = b''
        else:
            status, body = 200, b'{"ok":true}'
        result = addinfourl(BytesIO(body), headers, request.full_url, status)
        result.msg = 'Synthetic response'
        return result

    http_open = https_open


def memory_transport(monkeypatch, redirects):
    """Retain post_json/urlopen and replace only network I/O in its real opener."""
    handler = MemoryHttpHandler(redirects)

    def opener_factory(*handlers):
        assert any(isinstance(h, http_client.SameOriginRedirectHandler) for h in handlers)
        return build_opener(ProxyHandler({}), *handlers, handler)

    monkeypatch.setattr(http_client, 'build_opener', opener_factory)
    return handler


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
@pytest.mark.parametrize('destination', [
    'https://other.invalid/capture',
    'http://provider.invalid/capture',
    'https://provider.invalid:444/capture',
    '//other.invalid/capture',
    'https://user:private-value@provider.invalid/capture',
    'https://@provider.invalid/capture',
    'https://[broken',
    'https://provider.invalid:bad/capture',
    'https://provider.invalid\n/capture',
])
def test_production_opener_rejects_unsafe_redirect_before_second_request(monkeypatch, status, destination):
    handler = memory_transport(monkeypatch, [(status, destination)])
    with pytest.raises(ServiceError) as caught:
        http_client.post_json('https://provider.invalid/start', {}, KEY, 1)
    assert caught.value.code == ErrorCode.TOOL_UNAVAILABLE
    assert caught.value.retryable is False
    assert len(handler.calls) == 1
    assert handler.calls[0][2] == f'Bearer {KEY}'
    assert KEY not in str(caught.value) and 'private-value' not in str(caught.value)


@pytest.mark.parametrize('destination', ['/canonical', 'https://PROVIDER.invalid:443/canonical'])
@pytest.mark.parametrize('status', [301, 302, 303])
def test_production_opener_preserves_same_origin_auth_and_default_port(monkeypatch, status, destination):
    handler = memory_transport(monkeypatch, [(status, destination)])
    assert http_client.post_json('https://provider.invalid/start', {}, KEY, 1) == {'ok': True}
    assert len(handler.calls) == 2
    assert [call[1] for call in handler.calls] == ['POST', 'GET']
    assert all(call[2] == f'Bearer {KEY}' for call in handler.calls)


@pytest.mark.parametrize('last_status', [301, 302, 303, 307, 308])
def test_later_redirect_in_chain_cannot_leak_credentials(monkeypatch, last_status):
    handler = memory_transport(monkeypatch, [(302, '/next'), (last_status, 'http://provider.invalid/leak')])
    with pytest.raises(ServiceError):
        http_client.post_json('https://provider.invalid/start', {}, KEY, 1)
    assert len(handler.calls) == 2
    assert all(url.startswith('https://provider.invalid/') for url, _, _ in handler.calls)


@pytest.mark.parametrize('status', [307, 308])
def test_post_is_not_replayed_by_method_preserving_redirect(monkeypatch, status):
    handler = memory_transport(monkeypatch, [(status, '/next')])
    with pytest.raises(ServiceError) as caught:
        http_client.post_json('https://provider.invalid/start', {}, KEY, 1)
    assert caught.value.code == ErrorCode.TOOL_UNAVAILABLE and not caught.value.retryable
    assert len(handler.calls) == 1


@pytest.mark.parametrize('location', ['open', 'read'])
@pytest.mark.parametrize('error', [
    HTTPException('private-protocol-value'), BadStatusLine('private-protocol-value'),
    RemoteDisconnected('private-protocol-value'), IncompleteRead(b'private-protocol-value', 200),
])
def test_protocol_errors_are_sanitized_at_connection_and_body_boundaries(monkeypatch, location, error):
    calls = []

    class BrokenResponse(BytesIO):
        def read(self, *args):
            raise error

    def fake_open(*args, **kwargs):
        calls.append(args)
        if location == 'open':
            raise error
        return BrokenResponse()

    monkeypatch.setattr(http_client, 'urlopen', fake_open)
    with pytest.raises(ServiceError) as caught:
        http_client.post_json('https://provider.invalid', {}, KEY, 1)
    assert caught.value.code == ErrorCode.TOOL_UNAVAILABLE and caught.value.retryable
    assert 'private-protocol-value' not in str(caught.value)
    assert len(calls) == 1


def resource_skill(kind, resource):
    if kind == 'search':
        return WebSearchSkill(KEY, 'https://provider.invalid', transport=lambda *a: {
            'results': [{'title': 'source', 'url': resource, 'content': 'content'}]})
    if kind == 'image':
        return ImageGenSkill('https://provider.invalid', KEY, 'image-model',
                             transport=lambda *a: {'data': [{'url': resource}]})
    return BailianImageSkill('https://provider.invalid', KEY, transport=lambda *a: {
        'output': {'choices': [{'message': {'content': [{'image': resource}]}}]}})


@pytest.mark.parametrize('kind', ['search', 'image', 'bailian'])
@pytest.mark.parametrize('resource', [
    'https://[broken', 'https://[::1]suffix/image.png', 'https://:443/image.png',
    'https://resource.invalid:wrong/image.png', 'https://resource.invalid:65536/image.png',
    'https://resource.invalid:/image.png', 'https://resource.invalid\t/image.png',
    'https://@resource.invalid/image.png', 'https://user@resource.invalid/image.png',
    'https://:private-value@resource.invalid/image.png', 'file:///image.png',
])
def test_resource_urls_fail_closed_with_typed_sanitized_errors(kind, resource):
    with pytest.raises(ServiceError) as caught:
        resource_skill(kind, resource).run({'query': 'resource'})
    assert caught.value.code == ErrorCode.CONTRACT_MISMATCH and not caught.value.retryable
    assert 'private-value' not in str(caught.value)


@pytest.mark.parametrize('kind', ['search', 'image', 'bailian'])
@pytest.mark.parametrize('resource', [
    'https://[2001:db8::1]:8443/image.png?version=2',
    'http://resource.invalid/image%20name.png',
    'https://resource.invalid/image.png?signature=synthetic-value',
])
def test_valid_resource_urls_are_preserved_without_downloading(kind, resource):
    result = json.loads(resource_skill(kind, resource).run({'query': 'resource'}))
    actual = result['results'][0]['source_url'] if kind == 'search' else result['images'][0]['image_url']
    assert actual == resource


@pytest.mark.parametrize('url', ['file:///tmp/secret', 'https://user:private-value@provider.invalid', 'https://[broken'])
def test_invalid_transport_url_fails_before_open(monkeypatch, url):
    monkeypatch.setattr(http_client, 'urlopen', lambda *a, **k: pytest.fail('Invalid URL reached I/O'))
    with pytest.raises(ServiceError) as caught:
        http_client.post_json(url, {}, KEY, 1)
    assert caught.value.code == ErrorCode.INVALID_INPUT and not caught.value.retryable
    assert 'private-value' not in str(caught.value)


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity', '1e999', '-1e999'])
def test_transport_rejects_nonfinite_provider_numbers(monkeypatch, token):
    body = ('{"nested":[{"value":' + token + '}]}').encode()
    monkeypatch.setattr(http_client, 'urlopen', lambda *a, **k: BytesIO(body))
    with pytest.raises(ServiceError) as caught:
        http_client.post_json('https://provider.invalid', {}, KEY, 1)
    assert caught.value.code == ErrorCode.CONTRACT_MISMATCH and not caught.value.retryable


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), object()])
def test_transport_rejects_invalid_payload_before_io(monkeypatch, value):
    monkeypatch.setattr(http_client, 'urlopen', lambda *a, **k: pytest.fail('Invalid JSON reached I/O'))
    with pytest.raises(ServiceError) as caught:
        http_client.post_json('https://provider.invalid', {'nested': [value]}, KEY, 1)
    assert caught.value.code == ErrorCode.INVALID_INPUT and not caught.value.retryable


def test_transport_preserves_finite_numbers_exact_integers_and_numeric_words(monkeypatch):
    value = {'number': 1.25, 'amount': 9007199254740993, 'label': 'NaN Infinity'}
    def fake_open(request, **kwargs):
        assert json.loads(request.data) == value
        return BytesIO(json.dumps(value).encode())
    monkeypatch.setattr(http_client, 'urlopen', fake_open)
    assert http_client.post_json('https://provider.invalid', value, KEY, 1) == value


def image_result(encoded):
    return json.loads(ImageGenSkill('https://provider.invalid', KEY, 'image-model',
        transport=lambda *a: {'data': [{'b64_json': encoded}]}).run({'query': 'draw'}))


@pytest.mark.parametrize('encoded', [MOCK_PNG, JPEG, WEBP, WEBP_LOSSLESS])
def test_supported_raster_bytes_are_preserved(encoded):
    assert image_result(encoded)['images'] == [{'image_base64': encoded}]


@pytest.mark.parametrize('encoded', [MOCK_PNG, JPEG, WEBP, WEBP_LOSSLESS])
def test_truncated_image_framing_is_not_reported_as_completed(encoded):
    raw = base64.b64decode(encoded)
    for prefix in [raw[:4], raw[:12], raw[:-1]]:
        with pytest.raises(ServiceError) as caught:
            image_result(base64.b64encode(prefix).decode())
        assert caught.value.code == ErrorCode.CONTRACT_MISMATCH


@pytest.mark.parametrize('raw', [
    b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
    b'\xff\xd8\xff\xd9', b'RIFF\x04\x00\x00\x00WEBP',
    base64.b64decode(MOCK_PNG)[:-12] + b'not-an-IEND!!',
    base64.b64decode(MOCK_PNG)[:40] + b'\xff' + base64.b64decode(MOCK_PNG)[41:],
    base64.b64decode(WEBP)[:4] + b'\xff\xff\xff\xff' + base64.b64decode(WEBP)[8:],
])
def test_non_raster_and_corrupt_container_bytes_are_contract_failures(raw):
    with pytest.raises(ServiceError) as caught:
        image_result(base64.b64encode(raw).decode())
    assert caught.value.code == ErrorCode.CONTRACT_MISMATCH and not caught.value.retryable
