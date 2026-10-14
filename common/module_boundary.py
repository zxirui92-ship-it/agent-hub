"""Correlation and error helpers for imported modules; no orchestration decisions."""
from common.contracts import AgentResult, ErrorDetail
from datetime import datetime, timezone
import json
import logging


def correlation(request):
    return {key: getattr(request, key) for key in ('request_id', 'task_id', 'trace_id', 'capability_id')}


def result_for(request, **fields):
    result = AgentResult(**correlation(request), **fields)
    module = request.capability_id.split('.')[0]
    record = {'ts': datetime.now(timezone.utc).isoformat(), 'level': 'error' if result.error else 'info',
              'module': module, **correlation(request), 'status': result.status}
    if result.error:
        record['error_code'] = result.error.code.value
    logging.getLogger(f'agent_hub.{module}').log(
        logging.ERROR if result.error else logging.INFO, json.dumps(record, ensure_ascii=False))
    return result


def failure(request, code, message, *, retryable=False):
    ids = correlation(request)
    return result_for(request, status='failed', error=ErrorDetail(
        **{k: v for k, v in ids.items() if k != 'capability_id'},
        code=code, message=message, retryable=retryable))
