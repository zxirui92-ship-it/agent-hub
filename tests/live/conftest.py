"""Opt-in local diagnostics for paid tests; never log authorization headers."""
import json
import os
from pathlib import Path
import re
import time
from datetime import datetime, timezone

import pytest

from common.config_env import secret_values
from common import http_client


def sanitized(value):
    secrets = secret_values()
    def clean(item):
        if isinstance(item, dict):
            return {key: clean(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [clean(val) for val in item]
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, '[redacted]')
            # Redact before serialization, preserving nested JSON escape syntax.
            return re.sub(r'(?i)(Signature|OSSAccessKeyId|Expires)=([^&"\\\s]+)',
                          r'\1=[redacted]', item)
        return item
    return json.dumps(clean(value), ensure_ascii=False, default=str)


class LoggedResponse:
    def __init__(self, response, emit, started, call_id):
        self.response, self.emit = response, emit
        self.started, self.call_id = started, call_id

    def __enter__(self):
        self.response.__enter__()
        return self

    def __exit__(self, *args):
        return self.response.__exit__(*args)

    def read(self, *args):
        try:
            body = self.response.read(*args)
        except Exception as exc:
            self.emit('response_error', call_id=self.call_id, error=str(exc))
            raise
        self.emit('response', call_id=self.call_id,
                  seconds=round(time.perf_counter()-self.started, 3),
                  status=getattr(self.response, 'status', None),
                  body=body.decode('utf-8', errors='replace'))
        return body


@pytest.fixture(autouse=True)
def live_http_log(request, monkeypatch):
    directory = os.getenv('HUB_LIVE_LOG_DIR')
    if not directory:
        yield
        return
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    def emit(event, **fields):
        with (path / 'http.jsonl').open('a', encoding='utf-8') as log:
            log.write(sanitized({'time': datetime.now(timezone.utc).isoformat(),
                                'test': request.node.nodeid, 'event': event, **fields}) + '\n')
    original = http_client.urlopen
    count = 0
    def logged_open(req, *, timeout):
        nonlocal count
        count += 1
        started = time.perf_counter()
        emit('request', call_id=count, url=req.full_url, timeout=timeout,
             body=(req.data or b'').decode('utf-8', errors='replace'))
        try:
            response = original(req, timeout=timeout)
        except Exception as exc:
            emit('transport_error', call_id=count, seconds=round(time.perf_counter()-started, 3),
                 error_type=type(exc).__name__, error=str(exc), status=getattr(exc, 'code', None))
            raise
        return LoggedResponse(response, emit, started, count)
    monkeypatch.setattr(http_client, 'urlopen', logged_open)
    emit('test_start')
    try:
        yield
    finally:
        emit('test_end', http_calls=count)
