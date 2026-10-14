from copy import deepcopy
import json

import pytest

from common.errors import ErrorCode, ServiceError
from hub_platform.planner import DynamicPlanner, PlanningError
from hub_platform.registry import CapabilityRegistry
from tests.mocks.agents import manifest, obj, result


class ScriptedModel:
    """Recorded responses test control flow, not real semantic understanding."""
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, query):
        self.calls.append((system, json.loads(query)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)


def ready(steps):
    return {'status': 'ready', 'message': '按已注册能力执行任务。', 'steps': steps}


def order_steps(order_id='2025101234'):
    return [{'step_id': 's1', 'capability_id': 'm2.order_tracking',
             'inputs': {'order_id': {'literal': order_id}}}]


def test_single_task_uses_live_catalog_and_platform_owned_ids(registry):
    model = ScriptedModel(ready(order_steps()))
    outcome = DynamicPlanner(registry, model).plan('查询订单 2025101234')
    assert outcome.plan.goal == '查询订单 2025101234'
    assert outcome.plan.plan_id.startswith('plan-')
    assert len(outcome.plan.steps) == 1 and len(outcome.attempts) == 1
    system, query = model.calls[0]
    assert query['catalog'] == [item.model_dump(mode='json') for item in registry.list_capabilities()]
    assert 'input_schema' in query['catalog'][0] and 'output_schema' in query['catalog'][0]
    assert 'needs_clarification' in system and 'max_steps' in query


@pytest.mark.parametrize('status', ['needs_clarification', 'unsupported'])
def test_non_executable_decisions_have_no_plan(registry, status):
    model = ScriptedModel({'status': status, 'message': '请补充信息或改用已支持的任务。', 'steps': []})
    outcome = DynamicPlanner(registry, model).plan('一个请求')
    assert outcome.plan is None and outcome.decision.status == status
    assert len(model.calls) == 1


def test_new_capability_is_discovered_without_changing_planner():
    class Echo:
        def invoke(self, request):
            pytest.fail('Planning must not invoke any module')
    registry = CapabilityRegistry()
    model = ScriptedModel(ready([{'step_id': 's1', 'capability_id': 'partner.echo',
                                 'inputs': {'text': {'literal': 'hello'}}}]))
    planner = DynamicPlanner(registry, model)
    assert planner.plan('hello').decision.status == 'unsupported'
    assert not model.calls
    spec = manifest('partner.echo', '复述', '复述用户提供的文字',
                    obj(text={'type': 'string'}), obj(text={'type': 'string'}))
    registry.register(spec, Echo())
    outcome = planner.plan('复述 hello')
    assert outcome.plan.steps[0].capability_id == 'partner.echo'
    assert model.calls[0][1]['catalog'][0]['description'] == spec.description


@pytest.mark.parametrize('bad', [
    'not JSON', '[]',
    {'status': 'ready', 'message': '没有步骤', 'steps': []},
    {'status': 'needs_clarification', 'message': '订单号？', 'steps': order_steps()},
    {'status': 'ready', 'message': 'x', 'steps': order_steps(), 'extra': 1},
    ready([{'step_id': 's1', 'capability_id': 'missing', 'inputs': {}}]),
    ready([{'step_id': 's1', 'capability_id': 'm2.order_tracking', 'inputs': {}}]),
    ready([{'step_id': 's1', 'capability_id': 'm2.order_tracking', 'depends_on': ['s1'],
            'inputs': {'order_id': {'literal': '2025101234'}}}]),
    ready([{'step_id': 's1', 'capability_id': 'm2.order_tracking',
            'inputs': {'order_id': {'ref': 's99.data.order_id'}}}]),
])
def test_invalid_output_gets_one_repair_with_actionable_feedback(registry, bad):
    model = ScriptedModel(bad, ready(order_steps()))
    outcome = DynamicPlanner(registry, model).plan('查询订单 2025101234')
    assert len(model.calls) == 2
    assert [attempt.status for attempt in outcome.attempts] == ['invalid', 'accepted']
    repair = model.calls[1][1]['repair']
    assert repair['message'] and repair['error_code']
    assert outcome.plan.steps[0].inputs['order_id'].literal == '2025101234'


def test_repair_can_choose_clarification_instead_of_inventing_input(registry):
    model = ScriptedModel(ready([{'step_id': 's1', 'capability_id': 'm2.order_tracking'}]),
                          {'status': 'needs_clarification', 'message': '请提供订单号。'})
    result = DynamicPlanner(registry, model).plan('帮我查询订单')
    assert result.plan is None and result.decision.status == 'needs_clarification'


def test_repair_exhaustion_is_explicit(registry):
    model = ScriptedModel('bad', 'still bad', ready(order_steps()))
    with pytest.raises(PlanningError) as caught:
        DynamicPlanner(registry, model).plan('查询订单')
    assert len(model.calls) == len(caught.value.attempts) == 2
    assert caught.value.code == ErrorCode.CONTRACT_MISMATCH


def test_service_errors_do_not_trigger_plan_repair(registry, monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'unit-secret')
    model = ScriptedModel(ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'unit-secret service unavailable', retryable=False))
    with pytest.raises(PlanningError) as caught:
        DynamicPlanner(registry, model).plan('订单')
    assert len(model.calls) == 1 and not caught.value.retryable
    assert 'unit-secret' not in str(caught.value)


def test_step_limit_and_schema_still_use_existing_validator(registry):
    steps = order_steps() + [{'step_id': 's2', 'capability_id': 'm1.faq_chat',
                             'inputs': {'question': {'literal': '退货'}}}]
    model = ScriptedModel(ready(steps))
    with pytest.raises(PlanningError) as caught:
        DynamicPlanner(registry, model, max_steps=1, max_repairs=0).plan('两个任务')
    assert caught.value.code == ErrorCode.EXECUTION_LIMIT


def test_caller_context_is_not_mutated(registry):
    context = {'history': [{'messages': [{'role': 'user', 'content': '预算10万元'}]}]}
    before = deepcopy(context)
    DynamicPlanner(registry, ScriptedModel(ready(order_steps()))).plan('订单', context=context)
    assert context == before
