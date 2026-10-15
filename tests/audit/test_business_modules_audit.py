"""Offline audit: real M1/M3/M5/M6 with deterministic models and input fixtures.

Original defect assertions remain as expected-behavior regression checks.
Production modules run with deterministic models; no external service is used.
"""
from copy import deepcopy
from itertools import permutations
import json

import pytest

from agents.blackboard import Blackboard, BlackboardController, DataFusionModule, WeeklySource
from agents.multi_agent import PromotionAgent, ROLE_ORDER
from agents.plan_execute import WeeklyReportAgent
from agents.single_agent import ConversationMemory, SingleAgent
from common.contracts import AgentRequest
from common.errors import ErrorCode, ServiceError
from hub_platform.executor import Executor
from hub_platform.registry import CapabilityRegistry


SESSION_A = 'sess-aaaaaaaaaaaa'
SESSION_B = 'sess-bbbbbbbbbbbb'


class ScriptedTextModel:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, system, query):
        self.calls.append((system, query))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return json.dumps(response, ensure_ascii=False) if isinstance(response, dict) else response


class FakePromotionLLM:
    def __init__(self, fail_at=None, error=None):
        self.fail_at = fail_at
        self.error = error
        self.calls = []

    def __call__(self, prompt, system=None, **kwargs):
        self.calls.append((prompt, system))
        index = len(self.calls)
        if index == self.fail_at:
            raise self.error
        if system is not None:
            return '统一时间线：预热→正式活动→复盘。所有预算与建议待确认。'
        return f'建议：角色动作-{index}\n依据：已提供事实-{index}'


def request(capability, payload, context=None):
    return AgentRequest(request_id='req-000000000001', task_id='task-000000000001',
        trace_id='trace-0000000000000001', capability_id=capability,
        payload=deepcopy(payload), context=deepcopy(context or {}))


def fused(week='2026-W41', **overrides):
    return {'week': week, 'revenue_amount': 125001, 'order_count': 12,
        'conversion_rate': .03, 'anomaly': 'AUDIT_FACT:源记录不证明因果', **overrides}


def registry_of(*modules):
    registry = CapabilityRegistry()
    for module in modules:
        registry.register(module.manifest, module)
    return registry


@pytest.fixture
def source_documents():
    return {
        'order_basic': {'weeks': {
            '2026-W40': {'gmv_amount': 100001, 'order_count': 10, 'refund_rate': .01},
            '2026-W41': {'gmv_amount': 125001, 'order_count': 12, 'refund_rate': .02,
                'anomalies': [{'reason': 'AUDIT_HEAD:' + '事实' * 160 + ':AUDIT_TAIL'}]},
        }},
        'user_behavior': {'weeks': {
            '2026-W40': {'conversion_rate': .02, 'uv_count': 100},
            '2026-W41': {'conversion_rate': .03, 'uv_count': 100},
        }},
        'marketing_campaign': {'campaigns': [
            {'week': '2026-W41', 'name': 'AUDIT_CURRENT_CAMPAIGN', 'budget_amount': 101},
            {'week': '2026-W40', 'name': 'AUDIT_PREVIOUS_CAMPAIGN', 'budget_amount': 99},
        ]},
    }


def write_source(path, documents):
    for name, document in documents.items():
        (path / f'{name}.json').write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
    return WeeklySource(path)


# M1: model failures and interleaved users must not corrupt accepted history.
def test_m1_interleaved_sessions_payload_precedence_and_window_eviction():
    model = ScriptedTextModel('answer-a1', 'answer-b1', 'answer-a2', 'answer-b2', 'answer-a3')
    agent = SingleAgent(model, memory=ConversationMemory(4))
    for question, session in [('a1', SESSION_A), ('b1', SESSION_B), ('a2', SESSION_A),
                              ('b2', SESSION_B), ('a3', SESSION_A)]:
        result = agent.invoke(request('m1.faq_chat', {'question': question, 'session_id': session},
                                      {'session_id': SESSION_B if session == SESSION_A else SESSION_A}))
        assert result.status == 'completed'
        assert result.data['session_id'] == session
    histories = [json.loads(query)['history'] for _, query in model.calls]
    assert histories[0] == histories[1] == []
    assert [item['content'] for item in histories[2]] == ['a1', 'answer-a1']
    assert [item['content'] for item in histories[3]] == ['b1', 'answer-b1']
    assert [item['content'] for item in histories[4]] == ['a1', 'answer-a1', 'a2', 'answer-a2']
    assert [item['content'] for item in agent.memory.window(SESSION_A)] == ['a2', 'answer-a2', 'a3', 'answer-a3']


@pytest.mark.parametrize('bad,code', [
    ('', ErrorCode.CONTRACT_MISMATCH), (' \n\t', ErrorCode.CONTRACT_MISMATCH),
    (None, ErrorCode.CONTRACT_MISMATCH), (123, ErrorCode.CONTRACT_MISMATCH),
    (ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'fake offline', retryable=False), ErrorCode.TOOL_UNAVAILABLE),
    (RuntimeError('fake failure'), ErrorCode.INTERNAL_ERROR),
])
def test_m1_failed_turn_preserves_prior_history_and_recovers(bad, code):
    model = ScriptedTextModel('accepted', bad, 'recovered')
    agent = SingleAgent(model)
    first = request('m1.faq_chat', {'question': 'first', 'session_id': SESSION_A})
    assert agent.invoke(first).status == 'completed'
    before = agent.memory.window(SESSION_A)
    failure = agent.invoke(request('m1.faq_chat', {'question': 'failed turn', 'session_id': SESSION_A}))
    assert failure.status == 'failed' and failure.error.code == code
    assert agent.memory.window(SESSION_A) == before
    assert agent.invoke(request('m1.faq_chat', {'question': 'retry', 'session_id': SESSION_A})).status == 'completed'
    assert json.loads(model.calls[-1][1])['history'] == before
    assert first.payload == {'question': 'first', 'session_id': SESSION_A}


def test_m1_auto_sessions_and_separate_instances_never_share_history():
    model = ScriptedTextModel('one', 'two', 'three')
    agent = SingleAgent(model)
    one = agent.invoke(request('m1.faq_chat', {'question': 'one'}))
    two = agent.invoke(request('m1.faq_chat', {'question': 'two'}))
    assert one.data['session_id'] != two.data['session_id']
    assert json.loads(model.calls[1][1])['history'] == []
    fresh = SingleAgent(model)
    fresh.invoke(request('m1.faq_chat', {'question': 'three', 'session_id': one.data['session_id']}))
    assert json.loads(model.calls[2][1])['history'] == []


@pytest.mark.parametrize('session', ['not-a-session', 123, True, {'session': SESSION_A}])
def test_m1_invalid_context_session_rejected_before_model(session):
    model = ScriptedTextModel()
    result = SingleAgent(model).invoke(request('m1.faq_chat', {'question': '政策'}, {'session_id': session}))
    assert result.status == 'failed' and result.error.code == ErrorCode.INVALID_INPUT
    assert model.calls == []


# M3: every possible permutation checks fetch/report dependency enforcement.
@pytest.mark.parametrize('actions', list(permutations(('fetch', 'compare', 'anomaly', 'report'))))
def test_m3_exhaustive_action_order_dependency(actions):
    model = ScriptedTextModel({'actions': list(actions)}, '模型建议待验证')
    result = WeeklyReportAgent(model).invoke(request('m3.weekly_report', {'fused_data': fused()}))
    valid = actions[0] == 'fetch' and actions[-1] == 'report'
    if valid:
        assert result.status == 'completed'
        assert len(model.calls) == 2
        assert [step['status'] for step in result.data['steps']] == ['completed'] * 4
        assert '125001 分' in model.calls[1][1]
        assert 'AUDIT_FACT' in model.calls[1][1]
    else:
        assert result.status == 'failed' and result.error.code == ErrorCode.CONTRACT_MISMATCH
        assert len(model.calls) == 1 and result.data == {}


@pytest.mark.parametrize('bad,expected_code', [
    ('', ErrorCode.CONTRACT_MISMATCH), ('\t ', ErrorCode.CONTRACT_MISMATCH),
    (None, ErrorCode.CONTRACT_MISMATCH), (False, ErrorCode.CONTRACT_MISMATCH),
    (ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'unavailable', retryable=True), ErrorCode.TOOL_UNAVAILABLE),
    (RuntimeError('mock bug'), ErrorCode.INTERNAL_ERROR),
])
def test_m3_analysis_failure_cannot_publish_partial_report(bad, expected_code):
    model = ScriptedTextModel({'actions': ['fetch', 'compare', 'anomaly', 'report']}, bad)
    result = WeeklyReportAgent(model).invoke(request('m3.weekly_report', {'fused_data': fused()}))
    assert result.status == 'failed' and result.error.code == expected_code
    assert result.data == {} and len(model.calls) == 2


@pytest.mark.parametrize('current,previous', [
    ('2021-W01', '2020-W53'), ('2026-W01', '2025-W52'), ('2026-W41', '2026-W40'),
])
def test_m3_valid_adjacent_periods_and_exact_percent_units(current, previous):
    payload = {'fused_data': fused(current), 'previous_fused_data': fused(previous,
               revenue_amount=100001, order_count=10, conversion_rate=.02)}
    before = deepcopy(payload)
    result = WeeklyReportAgent(mode='local').invoke(request('m3.weekly_report', payload))
    assert result.status == 'completed'
    report = result.data['report_markdown']
    assert '销售额环比：+25.00%' in report
    assert '订单量环比：+20.00%' in report
    assert '转化率变化：+1.00 个百分点' in report
    assert '125001 分（1250.01 元）' in report
    assert payload == before


@pytest.mark.parametrize('previous', ['2026-W39', '2026-W41', '2026-W42', '2025-W40'])
def test_m3_nonadjacent_data_fails_before_planning(previous):
    model = ScriptedTextModel()
    result = WeeklyReportAgent(model).invoke(request('m3.weekly_report', {
        'fused_data': fused(), 'previous_fused_data': fused(previous)}))
    assert result.error.code == ErrorCode.INVALID_INPUT and model.calls == []


@pytest.mark.parametrize('rate', [float('-inf'), float('inf'), -.01, 1.01, True, '0.03'])
def test_m3_invalid_conversion_rates_fail_without_model_calls(rate):
    model = ScriptedTextModel()
    result = WeeklyReportAgent(model).invoke(request('m3.weekly_report', {'fused_data': fused(conversion_rate=rate)}))
    assert result.status == 'failed' and result.error.code == ErrorCode.INVALID_INPUT
    assert model.calls == []


@pytest.mark.parametrize('previous_nan', [False, True])
def test_m3_nan_metric_must_be_invalid_input(previous_nan):
    payload = {'fused_data': fused()}
    if previous_nan:
        payload['previous_fused_data'] = fused('2026-W40', conversion_rate=float('nan'))
    else:
        payload['fused_data']['conversion_rate'] = float('nan')
    result = WeeklyReportAgent(mode='local').invoke(request('m3.weekly_report', payload))
    assert result.status == 'failed' and result.error.code == ErrorCode.INVALID_INPUT


def test_m3_large_integer_cent_display_is_exact():
    amount = 9007199254740993
    result = WeeklyReportAgent(mode='local').invoke(request('m3.weekly_report', {'fused_data': fused(revenue_amount=amount)}))
    assert result.status == 'completed'
    assert f'{amount} 分（90071992547409.93 元）' in result.data['report_markdown']


# M6: corrupted sources must fail at the source boundary, not produce partial facts.
@pytest.mark.parametrize('name,mutation', [
    ('order_basic', 'missing_week'), ('user_behavior', 'missing_week'),
    ('order_basic', 'null_document'), ('user_behavior', 'list_document'),
    ('marketing_campaign', 'null_document'), ('marketing_campaign', 'wrong_collection'),
    ('order_basic', 'missing_required'), ('user_behavior', 'missing_required'),
    ('order_basic', 'bool_amount'), ('order_basic', 'float_amount'),
    ('order_basic', 'negative_orders'), ('order_basic', 'bad_refund_rate'),
    ('order_basic', 'bad_anomalies'), ('order_basic', 'bad_reason'),
    ('user_behavior', 'negative_conversion'), ('user_behavior', 'huge_conversion'),
    ('marketing_campaign', 'negative_budget'), ('marketing_campaign', 'missing_name'),
    ('marketing_campaign', 'wrong_campaign_type'),
])
def test_m6_corrupted_source_matrix_fails_closed(tmp_path, source_documents, name, mutation):
    documents = deepcopy(source_documents)
    current = documents[name]
    expected = ErrorCode.CONTRACT_MISMATCH
    if mutation == 'missing_week':
        del current['weeks']['2026-W41']
        expected = ErrorCode.NOT_FOUND
    elif mutation == 'null_document':
        documents[name] = None
    elif mutation == 'list_document':
        documents[name] = []
    elif mutation == 'wrong_collection':
        current['campaigns'] = {}
    elif mutation == 'missing_required':
        del current['weeks']['2026-W41']['gmv_amount' if name == 'order_basic' else 'conversion_rate']
    elif mutation == 'bool_amount':
        current['weeks']['2026-W41']['gmv_amount'] = True
    elif mutation == 'float_amount':
        current['weeks']['2026-W41']['gmv_amount'] = 125001.0
    elif mutation == 'negative_orders':
        current['weeks']['2026-W41']['order_count'] = -1
    elif mutation == 'bad_refund_rate':
        current['weeks']['2026-W41']['refund_rate'] = 1.1
    elif mutation == 'bad_anomalies':
        current['weeks']['2026-W41']['anomalies'] = {}
    elif mutation == 'bad_reason':
        current['weeks']['2026-W41']['anomalies'] = [{'reason': 1}]
    elif mutation == 'negative_conversion':
        current['weeks']['2026-W41']['conversion_rate'] = -.01
    elif mutation == 'huge_conversion':
        current['weeks']['2026-W41']['conversion_rate'] = 1.01
    elif mutation == 'negative_budget':
        current['campaigns'][0]['budget_amount'] = -1
    elif mutation == 'missing_name':
        del current['campaigns'][0]['name']
    elif mutation == 'wrong_campaign_type':
        current['campaigns'][0] = 'not-a-campaign'
    source = write_source(tmp_path, documents)
    result = DataFusionModule(source).invoke(request('m6.data_fusion', {'week': '2026-W41'}))
    assert result.status == 'failed' and result.error.code == expected
    assert result.data == {} and result.error.retryable is False


@pytest.mark.parametrize('name,field', [('order_basic', 'refund_rate'), ('user_behavior', 'conversion_rate')])
def test_m6_nan_in_source_must_fail_before_fusion(tmp_path, source_documents, name, field):
    source_documents[name]['weeks']['2026-W41'][field] = float('nan')
    source = write_source(tmp_path, source_documents)
    result = DataFusionModule(source).invoke(request('m6.data_fusion', {'week': '2026-W41'}))
    assert result.status == 'failed' and result.error.code == ErrorCode.CONTRACT_MISMATCH
    assert result.data == {}


def test_m6_reactive_updates_coalesce_and_recalculate_without_stale_insights(tmp_path, source_documents):
    controller = BlackboardController('2026-W41', write_source(tmp_path, source_documents))
    controller.run()
    original_event_count = len(controller.board.update_events)
    orders = controller.board.read('orders')
    orders['gmv_amount'] = 456
    orders['refund_rate'] = .25
    controller.board.write('orders', orders, 'audit_update')
    behavior = controller.board.read('behavior')
    behavior['conversion_rate'] = .4
    controller.board.write('behavior', behavior, 'audit_update')
    behavior['conversion_rate'] = .5
    controller.board.write('behavior', behavior, 'audit_update')
    controller.run()
    view = controller.fused_data()
    assert view['revenue_amount'] == 456 and view['conversion_rate'] == .5
    assert '50.00%' in view['anomaly'] and '25.00%' in view['anomaly']
    assert '3.00%' not in view['anomaly'] and '2.00%' not in view['anomaly']
    new_events = controller.board.update_events[original_event_count:]
    assert sum(e['event'] == 'process' and e['author'] == 'insight_agent' for e in new_events) == 1


def test_m6_callbacks_and_missing_defaults_are_independent_copies():
    board = Blackboard()
    seen = []
    board.subscribe('x', lambda entry: entry.value['nested'].append('first-mutated'))
    board.subscribe('x', lambda entry: seen.append(entry.value))
    board.write('x', {'nested': ['original']}, 'audit')
    assert seen == [{'nested': ['original']}]
    assert board.read('x') == {'nested': ['original']}
    default = {'nested': []}
    board.read('absent', default)['nested'].append('changed')
    assert default == {'nested': []}


# M5: stop at every failing stage and preserve authoritative input evidence.
@pytest.mark.parametrize('fail_at', range(1, 6))
@pytest.mark.parametrize('error,code,retryable', [
    (ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'temporary', retryable=True), ErrorCode.TOOL_UNAVAILABLE, True),
    (ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'permanent', retryable=False), ErrorCode.TOOL_UNAVAILABLE, False),
    (RuntimeError('unexpected mocked fault'), ErrorCode.INTERNAL_ERROR, False),
])
def test_m5_failure_each_stage_stops_calls_and_propagates_exact_failure(fail_at, error, code, retryable):
    model = FakePromotionLLM(fail_at, error)
    req = request('m5.promotion_plan', {'goal': 'audit promotion'})
    result = PromotionAgent(model).invoke(req)
    assert result.status == 'failed' and result.data == {}
    assert result.error.code == code and result.error.retryable is retryable
    assert len(model.calls) == fail_at
    for key in ('request_id', 'task_id', 'trace_id'):
        assert getattr(result, key) == getattr(req, key) == getattr(result.error, key)


@pytest.mark.parametrize('week,location', [('2025-W53', 'week'), ('0000-W01', 'week'),
    ('2025-W53', 'fused_data'), ('0000-W01', 'fused_data')])
def test_m5_impossible_iso_week_rejected_before_model(week, location):
    model = FakePromotionLLM()
    payload = {'goal': 'audit promotion', location: week if location == 'week' else fused(week)}
    result = PromotionAgent(model).invoke(request('m5.promotion_plan', payload))
    assert result.status == 'failed' and result.error.code == ErrorCode.INVALID_INPUT
    assert model.calls == []


def test_m5_nan_fused_metric_rejected_before_any_model_call():
    model = FakePromotionLLM()
    result = PromotionAgent(model).invoke(request('m5.promotion_plan', {
        'goal': 'audit promotion', 'fused_data': fused(conversion_rate=float('nan'))}))
    assert result.status == 'failed' and result.error.code == ErrorCode.INVALID_INPUT
    assert model.calls == []


@pytest.mark.parametrize('amount,decimal', [(0, '0.00'), (1, '0.01'), (99, '0.99'),
                                           (100, '1.00'), (101, '1.01'), (9007199254740993, '90071992547409.93')])
def test_m5_authoritative_budget_cents_exact_in_all_five_prompts(amount, decimal):
    model = FakePromotionLLM()
    req = request('m5.promotion_plan', {'goal': 'audit promotion', 'budget_amount': amount,
        'fused_data': fused(), 'report_markdown': 'HEAD\n' + 'background ' * 200 + '\nTAIL_FACT'})
    before = req.model_dump()
    result = PromotionAgent(model).invoke(req)
    assert result.status == 'completed' and len(model.calls) == 5
    for prompt, _ in model.calls:
        assert f'{amount} 分 = {decimal} 元' in prompt
        assert '125001 分 = 1250.01 元' in prompt
        assert 'TAIL_FACT' in prompt
        assert '角色建议不是事实' in prompt
    aggregate = model.calls[4][0]
    for index in range(1, 5):
        assert f'角色动作-{index}' in aggregate and f'已提供事实-{index}' in aggregate
    assert [role['role'] for role in result.data['roles']] == list(ROLE_ORDER)
    assert req.model_dump() == before


# Actual module chain with both current and previous M6 outputs (no mock business layer).
def test_full_business_chain_preserves_facts_and_dependency_order(tmp_path, source_documents):
    promotion_model = FakePromotionLLM()
    modules = [DataFusionModule(write_source(tmp_path, source_documents)), WeeklyReportAgent(mode='local'),
               PromotionAgent(promotion_model), SingleAgent(ScriptedTextModel('independent FAQ'))]
    plan = {
        'plan_id': 'plan-20261014-901', 'goal': 'audit M6→M3→M5 actual modules',
        'steps': [
            {'step_id': 's4', 'capability_id': 'm5.promotion_plan', 'depends_on': ['s3'], 'inputs': {
                'goal': {'literal': 'audit next week promotion'}, 'budget_amount': {'literal': 101},
                'fused_data': {'ref': 's1.data.fused_data'}, 'report_markdown': {'ref': 's3.data.report_markdown'}}},
            {'step_id': 's3', 'capability_id': 'm3.weekly_report', 'depends_on': ['s1', 's2'], 'inputs': {
                'fused_data': {'ref': 's1.data.fused_data'}, 'previous_fused_data': {'ref': 's2.data.fused_data'}}},
            {'step_id': 's2', 'capability_id': 'm6.data_fusion', 'inputs': {'week': {'literal': '2026-W40'}}},
            {'step_id': 's1', 'capability_id': 'm6.data_fusion', 'inputs': {'week': {'literal': '2026-W41'}}},
        ]}
    before = deepcopy(plan)
    report = Executor(registry_of(*modules)).execute(plan)
    assert report.status == 'completed'
    assert plan == before
    current = report.steps['s1'].result.data['fused_data']
    previous = report.steps['s2'].result.data['fused_data']
    assert current['conversion_rate'] == .03  # Must not invent orders/UV = .12.
    assert 'AUDIT_CURRENT_CAMPAIGN' in current['anomaly']
    assert 'AUDIT_PREVIOUS_CAMPAIGN' not in current['anomaly']
    assert 'AUDIT_PREVIOUS_CAMPAIGN' in previous['anomaly']
    assert report.steps['s3'].inputs == {'fused_data': current, 'previous_fused_data': previous}
    markdown = report.steps['s3'].result.data['report_markdown']
    assert '销售额环比：+25.00%' in markdown and '订单量环比：+20.00%' in markdown
    assert '转化率变化：+1.00 个百分点' in markdown
    assert report.steps['s4'].inputs['report_markdown'] == markdown
    for prompt, _ in promotion_model.calls:
        assert 'AUDIT_TAIL' in prompt and '无法计算 ROI' in prompt
        assert '101 分 = 1.01 元' in prompt
        assert markdown in prompt
    order = [event.step_id for event in report.events if event.status == 'running']
    assert set(order[:2]) == {'s1', 's2'} and order[2:] == ['s3', 's4']


@pytest.mark.parametrize('failure_stage', ['fusion', 'report', 'promotion'])
def test_business_chain_failure_blocks_only_dependents(tmp_path, source_documents, failure_stage):
    source = write_source(tmp_path, source_documents)
    report_model = ScriptedTextModel({'actions': ['report', 'fetch', 'compare', 'anomaly']})
    promotion_model = FakePromotionLLM(1, ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'fake outage')) if failure_stage == 'promotion' else FakePromotionLLM()
    faq_model = ScriptedTextModel('independent branch succeeds')
    modules = [DataFusionModule(source),
        WeeklyReportAgent(report_model) if failure_stage == 'report' else WeeklyReportAgent(mode='local'),
        PromotionAgent(promotion_model), SingleAgent(faq_model)]
    plan = {'plan_id': 'plan-20261014-902', 'goal': 'audit failure graph', 'steps': [
        {'step_id': 's1', 'capability_id': 'm6.data_fusion', 'inputs': {'week': {'literal': '2026-W42' if failure_stage == 'fusion' else '2026-W41'}}},
        {'step_id': 's2', 'capability_id': 'm3.weekly_report', 'depends_on': ['s1'], 'inputs': {'fused_data': {'ref': 's1.data.fused_data'}}},
        {'step_id': 's3', 'capability_id': 'm5.promotion_plan', 'depends_on': ['s2'], 'inputs': {
            'goal': {'literal': 'audit'}, 'report_markdown': {'ref': 's2.data.report_markdown'}}},
        {'step_id': 's4', 'capability_id': 'm1.faq_chat', 'depends_on': ['s3'], 'inputs': {'question': {'literal': 'dependent'}}},
        {'step_id': 's5', 'capability_id': 'm1.faq_chat', 'inputs': {'question': {'literal': 'independent'}}},
    ]}
    report = Executor(registry_of(*modules)).execute(plan)
    failed_step = {'fusion': 's1', 'report': 's2', 'promotion': 's3'}[failure_stage]
    expected_code = {'fusion': ErrorCode.NOT_FOUND, 'report': ErrorCode.CONTRACT_MISMATCH,
                     'promotion': ErrorCode.TOOL_UNAVAILABLE}[failure_stage]
    assert report.status == 'failed'
    assert report.steps[failed_step].error.code == expected_code
    assert report.steps['s4'].status == 'skipped'
    assert report.steps['s5'].status == 'completed' and len(faq_model.calls) == 1
    if failure_stage in ('fusion', 'report'):
        assert report.steps['s3'].status == 'skipped' and promotion_model.calls == []


def test_m5_target_week_survives_into_aggregation():
    """Target promotion week can differ from the historical evidence week."""
    model = FakePromotionLLM()
    result = PromotionAgent(model).invoke(request('m5.promotion_plan', {
        'goal': 'create promotion plan', 'week': '2026-W43', 'fused_data': fused('2026-W41')}))
    assert result.status == 'completed' and len(model.calls) == 5
    for prompt, _ in model.calls:
        assert '2026-W43' in prompt, 'Aggregator lost the explicit target promotion week'
        assert '2026-W41' in prompt
        assert '目标活动周（以此安排方案时间线）：2026-W43' in prompt
        assert '融合数据统计周：2026-W41（历史依据，不替代目标活动周）' in prompt


def test_m5_budget_summary_must_not_contradict_exact_budget_fact():
    amount = 9007199254740993
    model = FakePromotionLLM()
    result = PromotionAgent(model).invoke(request('m5.promotion_plan', {
        'goal': 'audit budget consistency', 'budget_amount': amount}))
    assert result.status == 'completed'
    for prompt, _ in model.calls[:4]:
        assert '预算：90071992547409.93 元' in prompt
        assert '预算：90071992547409.94 元' not in prompt


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity', '1e9999', '-1e9999'])
def test_m6_strict_json_boundary_rejects_nonfinite_values_even_in_unused_source_fields(
        tmp_path, source_documents, token):
    source = write_source(tmp_path, source_documents)
    path = tmp_path / 'marketing_campaign.json'
    text = path.read_text(encoding='utf-8')
    path.write_text(text[:-1] + ', "unused_metric": ' + token + '}', encoding='utf-8')
    result = DataFusionModule(source=source).invoke(request('m6.data_fusion', {'week': '2026-W41'}))
    assert result.status == 'failed' and result.error.code == ErrorCode.CONTRACT_MISMATCH
    assert not result.error.retryable and result.data == {}


@pytest.mark.parametrize('rate', [float('nan'), float('inf'), float('-inf')])
def test_m5_all_nonfinite_rates_fail_before_model_even_when_programmatically_injected(rate):
    model = FakePromotionLLM()
    result = PromotionAgent(model).invoke(request('m5.promotion_plan', {
        'goal': 'audit promotion', 'fused_data': fused(conversion_rate=rate)}))
    assert result.status == 'failed' and result.error.code == ErrorCode.INVALID_INPUT
    assert result.data == {} and model.calls == []


@pytest.mark.parametrize('target,evidence', [('2021-W01', '2020-W53'), ('2026-W53', '2026-W41'),
                                          ('0001-W01', '9999-W52')])
def test_m5_valid_calendar_weeks_need_not_match_or_be_adjacent(target, evidence):
    model = FakePromotionLLM()
    result = PromotionAgent(model).invoke(request('m5.promotion_plan', {
        'goal': 'audit promotion', 'week': target, 'fused_data': fused(evidence)}))
    assert result.status == 'completed' and len(model.calls) == 5
    for prompt, _ in model.calls:
        assert f'目标活动周（以此安排方案时间线）：{target}' in prompt
        assert f'融合数据统计周：{evidence}' in prompt


def test_m3_first_calendar_week_without_comparison_is_valid():
    result = WeeklyReportAgent(mode='local').invoke(request('m3.weekly_report', {
        'fused_data': fused('0001-W01')}))
    assert result.status == 'completed'
    assert '未提供上一周' in result.data['report_markdown']


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
def test_nonfinite_source_stops_actual_business_chain_before_any_model_calls(
        tmp_path, source_documents, value):
    source_documents['user_behavior']['weeks']['2026-W41']['conversion_rate'] = value
    report_model = ScriptedTextModel()
    promotion_model = FakePromotionLLM()
    modules = [DataFusionModule(write_source(tmp_path, source_documents)),
               WeeklyReportAgent(report_model), PromotionAgent(promotion_model)]
    plan = {'plan_id': 'plan-20261014-903', 'goal': 'reject corrupted numeric source', 'steps': [
        {'step_id': 's1', 'capability_id': 'm6.data_fusion',
         'inputs': {'week': {'literal': '2026-W41'}}},
        {'step_id': 's2', 'capability_id': 'm3.weekly_report', 'depends_on': ['s1'],
         'inputs': {'fused_data': {'ref': 's1.data.fused_data'}}},
        {'step_id': 's3', 'capability_id': 'm5.promotion_plan', 'depends_on': ['s2'],
         'inputs': {'goal': {'literal': 'audit'}, 'report_markdown': {'ref': 's2.data.report_markdown'}}},
    ]}
    report = Executor(registry_of(*modules)).execute(plan)
    assert report.status == 'failed'
    assert report.steps['s1'].error.code == ErrorCode.CONTRACT_MISMATCH
    assert report.steps['s1'].result.data == {}
    assert report.steps['s2'].status == report.steps['s3'].status == 'skipped'
    assert report_model.calls == promotion_model.calls == []


@pytest.mark.parametrize('token', ['NaN', 'Infinity', '-Infinity', '1e9999'])
def test_m3_standalone_source_uses_same_strict_json_boundary(tmp_path, source_documents, monkeypatch, token):
    import agents.plan_execute as m3

    write_source(tmp_path, source_documents)
    path = tmp_path / 'user_behavior.json'
    text = path.read_text(encoding='utf-8')
    path.write_text(text[:-1] + ', "unused_metric": ' + token + '}', encoding='utf-8')
    monkeypatch.setattr(m3, 'FIXTURES', tmp_path)
    with pytest.raises(ServiceError) as exc:
        m3.load_sample_view('2026-W41')
    assert exc.value.code == ErrorCode.CONTRACT_MISMATCH
