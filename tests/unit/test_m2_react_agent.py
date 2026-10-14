import json
import pytest

from agents.react_agent import ReActAgent, query_order, query_logistics
from common.errors import ErrorCode, ServiceError
from common.llm import ChatModel
from tests.contract.test_contracts import request_for
from tests.unit.test_m3_plan_execute import Model


def request(order_id='2025101234'):
    return request_for('m2.order_tracking', {'order_id': order_id})


def decision(action):
    return {'action': action, 'decision_summary': '读取缺失观察'}


def test_semantic_protocol_observations_drive_next_decision():
    model = Model(decision('query_logistics'), decision('query_order'))
    result = ReActAgent(model).invoke(request())
    assert result.status == 'completed' and result.data['order_amount'] == 69900
    assert result.data['actions'] == ['query_logistics', 'query_order']
    second_prompt = json.loads(model.calls[1][1])
    assert second_prompt['remaining_actions'] == ['query_order']
    assert second_prompt['observations'][0]['result']['tracking_number'] == 'mock-track-001'
    assert result.data['stop_reason'] == 'goal_achieved'


def test_amount_only_query_keeps_contract_completion_in_prompt():
    model = Model(decision('query_order'), decision('query_logistics'))
    req = request()
    req.payload['query'] = '查询该订单的订单金额与状态'
    result = ReActAgent(model).invoke(req)
    assert result.status == 'completed'
    assert json.loads(model.calls[1][1])['remaining_actions'] == ['query_logistics']
    assert '禁止输出 finish' in model.calls[1][0]


def test_repeated_action_reaches_limit_preserving_observations():
    model = Model(*[decision('query_order')] * 3)
    result = ReActAgent(model, max_rounds=3).invoke(request())
    assert result.error.code == ErrorCode.EXECUTION_LIMIT and len(model.calls) == 3
    assert len(result.data['observations']) == 3 and len(result.data['actions']) == 3


@pytest.mark.parametrize('response', ['not json', [], {'action': 'finish', 'decision_summary': 'done'},
    {'action': 'query_order', 'decision_summary': 'x', 'order_id': 'other'},
    {'action': 'query_order', 'decision_summary': ''}])
def test_invalid_model_choices_cannot_change_order_or_fake_finish(response):
    result = ReActAgent(Model(response)).invoke(request())
    assert result.error.code == ErrorCode.CONTRACT_MISMATCH
    assert result.data['actions'] == []


@pytest.mark.parametrize('order_id,code', [('missing', ErrorCode.NOT_FOUND), ('unavailable', ErrorCode.TOOL_UNAVAILABLE)])
def test_tool_errors_are_failed_not_empty_success(order_id, code):
    result = ReActAgent(mode='local').invoke(request(order_id))
    assert result.status == 'failed' and result.error.code == code
    assert result.data['actions'] == ['query_order']


@pytest.mark.parametrize('value', [True, 69900.0, -1])
def test_malformed_order_fact_rejected(value):
    tools = {'query_order': lambda oid: {**query_order(oid), 'order_amount': value}, 'query_logistics': query_logistics}
    assert ReActAgent(mode='local', tools=tools).invoke(request()).error.code == ErrorCode.CONTRACT_MISMATCH


@pytest.mark.parametrize('override', [{'order_id': 'wrong'}, {'tracking_number': 'wrong'}])
def test_inconsistent_logistics_fails(override):
    tools = {'query_order': query_order, 'query_logistics': lambda oid: {**query_logistics(oid), **override}}
    result = ReActAgent(mode='local', tools=tools).invoke(request())
    assert result.error.code == ErrorCode.CONTRACT_MISMATCH


def test_no_live_to_local_fallback():
    result = ReActAgent(ChatModel('', '', '')).invoke(request())
    assert result.error.code == ErrorCode.TOOL_UNAVAILABLE and result.data['actions'] == []


@pytest.mark.parametrize('rounds', [0, -1, True, 2.5])
def test_round_limit_validation(rounds):
    with pytest.raises(ValueError):
        ReActAgent(mode='local', max_rounds=rounds)


def test_invalid_input_and_runtime_tool_error():
    model = Model()
    assert ReActAgent(model).invoke(request_for('m2.order_tracking', {})).error.code == ErrorCode.INVALID_INPUT
    assert not model.calls
    def broken(oid):
        raise RuntimeError('broken')
    assert ReActAgent(mode='local', tools={'query_order': broken}).invoke(request()).error.code == ErrorCode.INTERNAL_ERROR
