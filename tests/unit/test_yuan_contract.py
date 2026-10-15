"""Public yuan migration: precision, amount safety and archive boundaries."""
import json
from pathlib import Path

import pytest

from agents.workflow.refund_graph import RefundWorkflow
from common.business_data import BusinessData
from common.errors import ErrorCode
from common.money import average_yuan, format_yuan, yuan_schema
from hub_platform.errors import HubError
from hub_platform.schema import check_schema, validate_data
from tests.contract.test_contracts import request_for


@pytest.mark.parametrize('amount,text', [(0, '0.00'), (1.2, '1.20'), (500, '500.00'),
    (500.01, '500.01'), (999999999999.99, '999999999999.99')])
def test_yuan_values_are_not_scaled_or_truncated(amount, text):
    check_schema(yuan_schema(), root=False)
    validate_data(amount, yuan_schema(), ErrorCode.INVALID_INPUT)
    assert format_yuan(amount) == text


@pytest.mark.parametrize('amount', [True, '1.00', None, float('nan'), float('inf'),
    -1, 1.001, 0.1 + 0.2, 1000000000000, 10**400])
def test_invalid_money_never_silently_rounds_or_overflows(amount):
    with pytest.raises(HubError):
        validate_data(amount, yuan_schema(), ErrorCode.INVALID_INPUT)


@pytest.mark.parametrize('amount,count,expected', [(.01, 2, .01), (.01, 3, .00),
    (2.01, 2, 1.01), (12680000, 66200, 191.54)])
def test_computed_money_uses_decimal_half_up(amount, count, expected):
    assert average_yuan(amount, count) == expected


@pytest.mark.parametrize('amount,status', [(499.99, 'completed'), (500.0, 'completed'), (500.01, 'waiting_approval')])
def test_fractional_yuan_refund_threshold_and_trace(amount, status):
    module = RefundWorkflow(order_loader=lambda _: {'order_amount': amount, 'order_status': 'paid'})
    result = module.invoke(request_for(module.manifest.capability_id,
        {'order_id': 'yuan-boundary', 'refund_amount': amount, 'reason': '退货'}))
    assert result.status == status, result.error
    assert result.data['state_view']['refund_amount'] == amount
    state = module.get_request_trace(result.request_id)[0]['state']
    assert state['refund_amount'] == amount
    assert format_yuan(amount) in ' '.join(state['history'])


def test_import_reader_converts_once_without_modifying_archive():
    directory = Path(__file__).resolve().parents[2] / 'data/group02'
    original = (directory / 'order_basic.json').read_bytes()
    raw = next(row for row in json.loads(original) if row['order_id'] == '2025100003')
    assert raw['order_amount'] == 12900
    source = BusinessData(directory)
    assert source.order('2025100003')['order_amount'] == 129.0
    assert source.order('2025100003')['order_amount'] == 129.0
    assert (directory / 'order_basic.json').read_bytes() == original


def test_old_cent_payload_cannot_approve_new_yuan_order():
    module = RefundWorkflow(order_loader=lambda _: {'order_amount': 129.0, 'order_status': 'paid'})
    result = module.invoke(request_for(module.manifest.capability_id,
        {'order_id': 'yuan-order', 'refund_amount': 12900, 'reason': '退货'}))
    assert result.status == 'failed' and result.error.code == ErrorCode.INVALID_INPUT


def test_excel_reconciliation_uses_same_yuan_unit_as_reader():
    from scripts.audit_group02 import normalize
    assert normalize(129, 'order_amount', excel=True) == normalize(129.0, 'order_amount')
    assert normalize(1.01, 'refund_amount', excel=True) == normalize(1.01, 'refund_amount')
