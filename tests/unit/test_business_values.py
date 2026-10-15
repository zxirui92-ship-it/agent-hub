"""Shared business-boundary regression controls; no external model or service."""
import json

import pytest

from common.errors import ErrorCode, ServiceError
from common.iso_week import week_schema, week_start
from common.json_data import strict_json_loads
from common.llm import json_object
from common.money import format_cents
from common.weekly_contract import previous_week
from hub_platform.errors import HubError
from hub_platform.schema import check_schema, validate_data


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity', '1e9999', '-1e9999'])
@pytest.mark.parametrize('wrapper', ['{}', '{{"values": [{{"value": {}}}]}}'])
def test_strict_json_rejects_nonfinite_values_at_any_depth(token, wrapper):
    with pytest.raises(ValueError):
        strict_json_loads(wrapper.format(token))


@pytest.mark.parametrize('encode', [str, lambda value: value.encode(), lambda value: bytearray(value.encode())])
def test_strict_json_preserves_valid_values_and_exact_integers(encode):
    data = {'huge_integer': 10**400 + 1, 'rate': 0.125, 'tiny': 1e-300,
            'description': 'NaN and Infinity are text', 'enabled': True, 'missing': None}
    assert strict_json_loads(encode(json.dumps(data, allow_nan=False))) == data


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity', '1e9999', '-1e9999'])
def test_model_json_boundary_rejects_nonfinite_values_before_consumers(token):
    with pytest.raises(ServiceError) as exc:
        json_object('{"details": [{"unused_metric": ' + token + '}]}')
    assert exc.value.code == ErrorCode.CONTRACT_MISMATCH
    assert not exc.value.retryable


def test_model_json_boundary_keeps_ordinary_json_semantics():
    data = {'action': 'fetch', 'description': 'Infinity is text', 'amount': 9007199254740993,
            'rate': .03, 'active': True, 'other': None}
    assert json_object(json.dumps(data, allow_nan=False)) == data


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), True, '0.5', 1 + 2j])
@pytest.mark.parametrize('code', [ErrorCode.INVALID_INPUT, ErrorCode.CONTRACT_MISMATCH])
def test_numeric_schema_without_bounds_rejects_nonfinite_and_non_json_numbers(value, code):
    with pytest.raises(HubError) as exc:
        validate_data({'rate': value}, {'type': 'object', 'properties': {'rate': {'type': 'number'}}}, code, 's1')
    assert exc.value.code == code
    assert 'rate' in str(exc.value)
    assert exc.value.step_id == 's1'


@pytest.mark.parametrize('value', [0, 1, 0.0, 1.0, 0.125, -0.25, 1e308, 10**400])
def test_numeric_schema_preserves_finite_numbers_and_arbitrary_exact_integers(value):
    validate_data(value, {'type': 'number'}, ErrorCode.INVALID_INPUT)


@pytest.mark.parametrize('week', ['2025-W53', '0000-W01', '9999-W53', '2026-W00',
                                 '2026-W54', '2026-W1', '2026-W41\n'])
def test_week_schema_checks_actual_calendar_and_canonical_text(week):
    with pytest.raises(ValueError):
        week_start(week)
    with pytest.raises(HubError) as exc:
        validate_data(week, week_schema(), ErrorCode.INVALID_INPUT)
    assert exc.value.code == ErrorCode.INVALID_INPUT


@pytest.mark.parametrize('week', ['0001-W01', '2020-W53', '2021-W01', '2026-W53', '9999-W52'])
def test_week_schema_accepts_real_boundary_and_53_week_years(week):
    assert week_start(week).isoweekday() == 1
    validate_data(week, week_schema(), ErrorCode.INVALID_INPUT)


def test_previous_week_keeps_four_digit_year_and_reports_calendar_underflow():
    assert previous_week('0001-W02') == '0001-W01'
    assert previous_week('2021-W01') == '2020-W53'
    with pytest.raises(ValueError):
        previous_week('0001-W01')


@pytest.mark.parametrize('kind,format_name', [('string', 'email'), ('integer', 'iso-week'),
                                           ('string', 'date-time')])
def test_schema_profile_does_not_silently_allow_other_formats(kind, format_name):
    with pytest.raises(HubError) as exc:
        check_schema({'type': kind, 'format': format_name}, root=False)
    assert exc.value.code == ErrorCode.UNSUPPORTED_SCHEMA


def test_iso_week_format_is_registered_as_an_explicit_supported_constraint():
    check_schema(week_schema(), root=False)


@pytest.mark.parametrize('amount,expected', [(0, '0.00'), (1, '0.01'), (99, '0.99'),
    (100, '1.00'), (101, '1.01'), (-1, '-0.01'), (-101, '-1.01'),
    (9007199254740991, '90071992547409.91'), (9007199254740992, '90071992547409.92'),
    (9007199254740993, '90071992547409.93'), (10**400 + 1, '1' + '0' * 398 + '.01')])
def test_integer_cent_formatting_is_exact(amount, expected):
    assert format_cents(amount) == expected


@pytest.mark.parametrize('amount', [True, 1.0, '1', None])
def test_integer_cent_formatter_does_not_coerce_invalid_input(amount):
    with pytest.raises(TypeError):
        format_cents(amount)
