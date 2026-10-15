from copy import deepcopy
import json

import pytest

from agents.plan_execute import WeeklyReportAgent, WeeklyReportPlanner, load_sample_view, _previous_week
from common.errors import ErrorCode, ServiceError
from tests.contract.test_contracts import request_for, SAMPLES


class Model:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, system, query):
        self.calls.append((system, query))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, str) else json.dumps(response)


def invoke(payload=None, model=None):
    return WeeklyReportAgent(model, mode='live' if model else 'local').invoke(
        request_for('m3.weekly_report', deepcopy(payload if payload is not None else SAMPLES[2])))


def test_real_computations_and_structured_steps():
    payload = {'fused_data': load_sample_view('2026-W41'), 'previous_fused_data': load_sample_view('2026-W40')}
    before = deepcopy(payload)
    result = invoke(payload)
    assert result.status == 'completed'
    report = result.data['report_markdown']
    assert '+8.09%' in report and '-0.02 个百分点' in report
    assert '12684300.00 元' in report and '84562' in report
    assert all(s['status'] == 'completed' and s['result_summary'] for s in result.data['steps'])
    assert [s['step_id'] for s in result.data['steps']] == ['s1', 's2', 's3', 's4']
    assert payload == before


def test_m6_data_never_mixes_with_unrelated_local_history():
    result = invoke()
    report = result.data['report_markdown']
    assert '120000.00 元' in report and '未提供上一周' in report
    assert '1173465000' not in report and '+8.09%' not in report


def test_zero_previous_denominator_is_explicit():
    payload = deepcopy(SAMPLES[2])
    payload['previous_fused_data'] = {**payload['fused_data'], 'week': '2026-W40', 'revenue_amount': 0.0, 'order_count': 0}
    assert '上周为零' in invoke(payload).data['report_markdown']


@pytest.mark.parametrize('payload', [{}, {'week': '2026-W41'}, {'fused_data': {'week': '2026-W41'}},
    {'fused_data': {**SAMPLES[2]['fused_data'], 'revenue_amount': True}},
    {'fused_data': {**SAMPLES[2]['fused_data'], 'revenue_amount': 1.001}},
    {'fused_data': {**SAMPLES[2]['fused_data'], 'week': '2025-W53'}},
    {**SAMPLES[2], 'previous_fused_data': {**SAMPLES[2]['fused_data'], 'week': '2026-W39'}}])
def test_invalid_payloads_fail_before_model(payload):
    model = Model()
    result = invoke(payload, model)
    assert result.status == 'failed' and result.error.code == ErrorCode.INVALID_INPUT
    assert model.calls == []


def test_iso_previous_week_includes_year_with_week_53():
    assert _previous_week('2021-W01') == '2020-W53'
    assert _previous_week('2026-W01') == '2025-W52'


def test_missing_fixture_week_is_not_reported_as_zero_data():
    with pytest.raises(ServiceError) as exc:
        load_sample_view('2026-W42')
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_model_plan_is_executed_and_facts_remain_in_report():
    model = Model({'actions': ['fetch', 'anomaly', 'compare', 'report']}, '建议核对转化指标口径。')
    result = invoke(model=model)
    assert result.status == 'completed' and len(model.calls) == 2
    assert result.data['steps'][1]['description'] == '分析输入异常'
    assert '120000.00 元' in model.calls[1][1]
    assert '120000.00 元' in result.data['report_markdown']
    assert '模型建议（待验证）' in result.data['report_markdown']


@pytest.mark.parametrize('response', ['bad json', {'actions': ['report', 'fetch', 'compare', 'anomaly']},
    {'actions': ['fetch', 'fetch', 'anomaly', 'report']}, {'actions': ['fetch', {}, 'anomaly', 'report']}])
def test_invalid_model_plan_does_not_silently_fall_back(response):
    result = invoke(model=Model(response))
    assert result.status == 'failed' and result.error.code == ErrorCode.CONTRACT_MISMATCH


def test_model_service_error_is_preserved():
    result = invoke(model=Model(ServiceError(ErrorCode.TOOL_UNAVAILABLE, '模型暂不可用')))
    assert result.error.code == ErrorCode.TOOL_UNAVAILABLE and result.error.retryable
    assert result.task_id == 'task-000000000001'


def test_wrong_capability_is_rejected():
    result = WeeklyReportAgent(mode='local').invoke(request_for('m5.promotion_plan', SAMPLES[2]))
    assert result.error.code == ErrorCode.CONTRACT_MISMATCH
