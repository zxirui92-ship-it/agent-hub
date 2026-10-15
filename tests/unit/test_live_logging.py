import io
import json

import pytest

from tests.live.conftest import LoggedResponse, sanitized


def test_log_redacts_secrets_and_signed_url(monkeypatch):
    monkeypatch.setenv('BAILIAN_API_KEY', 'secret-test-value')
    value = json.loads(sanitized({'response': 'secret-test-value',
        'url': 'https://example.com/image?Signature=abc&Expires=123&OSSAccessKeyId=xyz'}))
    assert value['response'] == '[redacted]'
    assert 'abc' not in value['url'] and 'xyz' not in value['url']


def test_log_nested_json_response_remains_parseable():
    body = json.dumps({'image_url': 'https://example.com/i?Signature=abc'})
    result = json.loads(sanitized({'body': body}))
    assert json.loads(result['body'])['image_url'].endswith('Signature=[redacted]')


def test_log_preserves_response_bytes_and_closes():
    stream = io.BytesIO(b'{"answer":"ok"}')
    events = []
    with LoggedResponse(stream, lambda event, **data: events.append((event,data)), 0, 1) as response:
        assert response.read() == b'{"answer":"ok"}'
    assert stream.closed
    assert events[0][1]['body'] == '{"answer":"ok"}'


def test_log_does_not_swallow_read_failure():
    class Broken:
        def read(self):
            raise TimeoutError('read timed out')
    events = []
    with pytest.raises(TimeoutError):
        LoggedResponse(Broken(), lambda event, **data: events.append(event), 0, 1).read()
    assert events == ['response_error']
