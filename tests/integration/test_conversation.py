import json

from agents.multi_agent import PromotionAgent
from agents.router.config import Settings
from agents.router.factory import create_agent
from common.errors import ErrorCode
from hub_platform.conversation import Conversation
from hub_platform.planner import DynamicPlanner
from hub_platform.registry import CapabilityRegistry
from tests.mocks.agents import MOCK_TYPES
from tests.unit.test_m5_multi_agent import FakeLLM
from tests.unit.test_planner import ScriptedModel, order_steps, ready


def test_two_different_composite_tasks_execute_different_graphs(registry, load_plan):
    operations, refund = load_plan('operations'), load_plan('refund_waiting')
    model = ScriptedModel(ready(operations['steps']), ready(refund['steps']))
    chat = Conversation(DynamicPlanner(registry, model))
    first = chat.submit('融合第41周数据，生成周报，再制定大促方案')
    second = chat.submit('查询订单2025101234，并以不再需要为由申请整单退款')
    assert first.status == 'completed' and second.status == 'waiting_approval'
    assert {step.capability_id for step in first.plan.steps} == {'m6.data_fusion', 'm3.weekly_report', 'm5.promotion_plan'}
    assert {step.capability_id for step in second.plan.steps} == {'m2.order_tracking', 'm7.refund_approval'}
    assert first.task_id != second.task_id and first.session_id == second.session_id
    assert first.report.steps['s3'].inputs['report_markdown'] == first.report.steps['s2'].result.data['report_markdown']
    assert second.report.steps['s2'].inputs['refund_amount'] == second.report.steps['s1'].result.data['order_amount']


def test_clarification_retains_original_goal_and_user_correction(registry, load_plan):
    steps = load_plan('operations')['steps']
    steps[0]['inputs']['budget_amount'] = {'literal': 10000000}
    model = ScriptedModel({'status': 'needs_clarification', 'message': '请提供统计周次。'}, ready(steps))
    chat = Conversation(DynamicPlanner(registry, model))
    question = chat.submit('分析经营数据并制定大促，预算8万元')
    assert question.status == 'needs_clarification' and question.report is None
    answer = chat.submit('2026年第41周，预算改成10万元')
    assert answer.status == 'completed'
    assert answer.task_id == question.task_id and answer.trace_id == question.trace_id
    prompt_context = model.calls[1][1]['context']['active_task']
    assert [m['role'] for m in prompt_context['messages']] == ['user', 'assistant', 'user']
    assert '预算8万元' in prompt_context['messages'][0]['content']
    assert '改成10万元' in prompt_context['messages'][2]['content']
    assert answer.report.steps['s3'].inputs['budget_amount'] == 10000000


def test_only_session_metadata_reaches_modules(registry):
    module = registry.get('m2.order_tracking')
    original = module.invoke
    calls = []
    def capture(request):
        calls.append(request)
        return original(request)
    module.invoke = capture
    chat = Conversation(DynamicPlanner(registry, ScriptedModel(ready(order_steps()))))
    response = chat.submit('查订单2025101234，我此前还讨论过其它事情')
    assert response.status == 'completed'
    assert calls[0].context == {'session_id': response.session_id}
    assert calls[0].payload == {'order_id': '2025101234'}


def test_prior_results_are_available_without_reexecuting_completed_steps(registry):
    first_step = [{'step_id': 's1', 'capability_id': 'm2.order_tracking',
                   'inputs': {'order_id': {'literal': 'order-low'}}}]
    next_step = [{'step_id': 's1', 'capability_id': 'm7.refund_approval', 'inputs': {
        'order_id': {'literal': 'order-low'}, 'refund_amount': {'literal': 19900},
        'reason': {'literal': '不再需要'}}}]
    model = ScriptedModel(ready(first_step), ready(next_step))
    chat = Conversation(DynamicPlanner(registry, model))
    chat.submit('查询订单 order-low')
    response = chat.submit('给刚查的订单申请整单退款，原因是不再需要')
    history = model.calls[1][1]['context']['history']
    assert history[0]['report']['steps']['s1']['result']['data']['order_amount'] == 19900
    assert response.status == 'completed' and len(response.report.steps) == 1
    assert response.report.steps['s1'].capability_id == 'm7.refund_approval'


def test_session_copies_and_reset_do_not_share_module_or_history_state(registry):
    chat = Conversation(DynamicPlanner(registry, ScriptedModel(ready(order_steps()))))
    other = Conversation(DynamicPlanner(registry, ScriptedModel()))
    response = chat.submit('查订单2025101234')
    response.report.steps['s1'].result.data['order_amount'] = -1
    snapshot = chat.context
    snapshot.active_task.messages.clear()
    assert chat.context.active_task.messages
    assert chat.context.active_task.report.steps['s1'].result.data['order_amount'] == 69900
    assert other.context.active_task is None and not other.context.history
    old_id = chat.context.session_id
    chat.reset()
    assert chat.context.session_id != old_id and chat.context.active_task is None


def test_preview_and_clarification_do_not_call_modules(registry):
    def forbidden(request):
        raise AssertionError('Must not execute a preview')
    registry.get('m2.order_tracking').invoke = forbidden
    model = ScriptedModel(ready(order_steps()))
    response = Conversation(DynamicPlanner(registry, model)).submit('查订单', execute=False)
    assert response.status == 'ready' and response.plan and response.report is None


def test_invalid_plan_never_invokes_modules(registry):
    calls = []
    registry.get('m2.order_tracking').invoke = lambda request: calls.append(request)
    model = ScriptedModel('bad', 'bad')
    response = Conversation(DynamicPlanner(registry, model)).submit('查订单')
    assert response.status == 'failed' and response.error.code == ErrorCode.CONTRACT_MISMATCH
    assert not calls and response.report is None and len(model.calls) == 2


def test_execution_failure_is_not_automatically_replanned(registry, load_plan):
    plan = load_plan('failure')
    model = ScriptedModel(ready(plan['steps']))
    response = Conversation(DynamicPlanner(registry, model)).submit('查询不存在的订单并退款')
    assert response.status == 'failed' and len(model.calls) == 1
    assert response.report.steps['s2'].status == 'skipped'


def test_waiting_task_is_not_rerun_as_approval(registry, load_plan):
    model = ScriptedModel(ready(load_plan('refund_waiting')['steps']), ready(order_steps()))
    chat = Conversation(DynamicPlanner(registry, model))
    first = chat.submit('订单2025101234整单退款')
    second = chat.submit('我同意了，继续')
    assert first.status == second.status == 'waiting_approval'
    assert len(model.calls) == 1 and second.report == first.report
    chat.new_task()
    third = chat.submit('重新查询订单2025101234')
    assert third.task_id != first.task_id and third.status == 'completed'
    assert chat.context.history[0].report.status == 'waiting_approval'


def test_dynamic_plan_with_real_m4_and_m5_modules(load_plan):
    registry = CapabilityRegistry()
    model = FakeLLM()
    m4, m5 = create_agent(Settings(mode='mock')), PromotionAgent(model)
    replacements = {m4.manifest.capability_id: m4, m5.manifest.capability_id: m5}
    for cls in MOCK_TYPES:
        module = replacements.get(cls.manifest.capability_id) or cls()
        registry.register(module.manifest, module)
    steps = load_plan('operations')['steps'] + [{'step_id': 's4', 'capability_id': m4.manifest.capability_id,
                                               'inputs': {'query': {'literal': 'kb_qa: 退款政策'}}}]
    planner_model = ScriptedModel(ready(steps))
    response = Conversation(DynamicPlanner(registry, planner_model)).submit('分析第41周经营，制定大促方案，同时查退款政策')
    assert response.status == 'completed' and len(model.prompts) == 5
    assert json.loads(response.report.final_results['s4']['result'])['mode'] == 'local'
