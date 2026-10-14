import json
import pytest

from agents.single_agent import SingleAgent, ConversationMemory
from common.errors import ErrorCode, ServiceError
from common.llm import ChatModel
from tests.contract.test_contracts import request_for
from tests.unit.test_m3_plan_execute import Model


def request(question='退货政策', session='sess-000000000001'):
    return request_for('m1.faq_chat', {'question': question, 'session_id': session})


def test_two_tools_one_model_and_window_context(caplog):
    model = Model('样例：七天退货', '需商品完好', '请联系售后')
    agent = SingleAgent(model, memory=ConversationMemory(2))
    caplog.set_level('INFO')
    first = agent.invoke(request())
    second = agent.invoke(request('那有什么条件？'))
    agent.invoke(request('还有呢'))
    assert first.status == second.status == 'completed'
    assert len(model.calls) == 3
    context = json.loads(model.calls[1][1])
    assert context['history'] == [{'role': 'user', 'content': '退货政策'},
                                  {'role': 'assistant', 'content': '样例：七天退货'}]
    assert set(context['tool_results']) == {'lookup_faq', 'get_service_policy'}
    assert len(json.loads(model.calls[2][1])['history']) == 2
    assert any('get_service_policy' in r.message for r in caplog.records)


def test_session_isolation_context_propagation_and_copy():
    model = Model('a', 'b', 'c')
    agent = SingleAgent(model)
    first = request()
    first.payload.pop('session_id')
    first.context = {'session_id': 'sess-000000000001'}
    assert agent.invoke(first).data['session_id'] == first.context['session_id']
    snapshot = agent.memory.window(first.context['session_id'])
    snapshot[0]['content'] = 'mutated'
    agent.invoke(request(session='sess-000000000002'))
    assert json.loads(model.calls[1][1])['history'] == []
    agent.invoke(request('继续'))
    assert json.loads(model.calls[2][1])['history'][0]['content'] == '退货政策'


@pytest.mark.parametrize('response,code', [('', ErrorCode.CONTRACT_MISMATCH),
    ('   ', ErrorCode.CONTRACT_MISMATCH), (ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'offline'), ErrorCode.TOOL_UNAVAILABLE),
    (RuntimeError('broken'), ErrorCode.INTERNAL_ERROR)])
def test_model_failure_does_not_create_success_or_memory(response, code):
    agent = SingleAgent(Model(response))
    req = request()
    result = agent.invoke(req)
    assert result.status == 'failed' and result.error.code == code
    assert result.trace_id == req.trace_id and result.error.request_id == req.request_id
    assert agent.memory.window(req.payload['session_id']) == []


@pytest.mark.parametrize('payload', [{}, {'question': '  '}, {'question': 'x', 'session_id': 'u1001'},
                                      {'question': 'x', 'extra': 1}])
def test_input_errors_do_not_call_model(payload):
    model = Model()
    result = SingleAgent(model).invoke(request_for('m1.faq_chat', payload))
    assert result.error.code == ErrorCode.INVALID_INPUT and not model.calls


def test_unconfigured_live_fails_and_mock_is_labeled():
    assert SingleAgent(ChatModel('', '', '')).invoke(request()).error.code == ErrorCode.TOOL_UNAVAILABLE
    assert 'Mock' in SingleAgent(mode='mock').invoke(request()).data['answer']


@pytest.mark.parametrize('size', [0, -1, True, 1.5])
def test_window_size_validation(size):
    with pytest.raises(ValueError):
        ConversationMemory(size)
