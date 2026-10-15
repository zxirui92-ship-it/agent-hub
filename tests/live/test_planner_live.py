"""Actual planner model behavior; all business execution remains mocked."""
import json
from pathlib import Path

import pytest

from hub_platform.executor import Executor
from hub_platform.planner import DynamicPlanner, configured_model

pytestmark = [pytest.mark.live, pytest.mark.planner_live]
CASES = json.loads((Path(__file__).parents[1] / 'fixtures/planner_semantic_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', CASES, ids=[case['case_id'] for case in CASES])
def test_real_planner_semantics(registry, case, record_property):
    model = configured_model()
    if not all((model.base_url, model.api_key, model.model)):
        pytest.skip('Planner LLM service not configured')
    outcome = DynamicPlanner(registry, model).plan(case['query'])
    record_property('model', model.model)
    record_property('planning_result', outcome.model_dump_json())
    assert outcome.decision.status == case['expected_status'], outcome.model_dump_json()
    selected = {step.capability_id for step in outcome.plan.steps} if outcome.plan else set()
    assert selected == set(case['expected_capabilities'])
    if outcome.plan:
        report = Executor(registry).execute(outcome.plan)
        record_property('mock_execution', report.model_dump_json())
        assert report.status in ('completed', 'waiting_approval'), report.model_dump_json()
        if case['case_id'] == 'operations_promotion':
            promotion = next(item for item in report.steps.values() if item.capability_id == 'm5.promotion_plan')
            assert promotion.inputs['budget_amount'] == 100000.0
            assert 'report_markdown' in promotion.inputs


def test_real_planner_multiturn_clarification(registry, record_property):
    from hub_platform.conversation import Conversation
    model = configured_model()
    if not all((model.base_url, model.api_key, model.model)):
        pytest.skip('Planner LLM service not configured')
    chat = Conversation(DynamicPlanner(registry, model))
    first = chat.submit('帮我查一下订单物流，我还没有提供订单号。')
    record_property('first_turn', first.model_dump_json())
    assert first.status == 'needs_clarification'
    second = chat.submit('订单号是2025101234。')
    record_property('second_turn', second.model_dump_json())
    assert second.status == 'completed'
    assert first.task_id == second.task_id and first.trace_id == second.trace_id
    assert {step.capability_id for step in second.plan.steps} == {'m2.order_tracking'}
    order = next(iter(second.report.steps.values()))
    assert order.inputs['order_id'] == '2025101234'


def test_real_planner_respects_approval_before_answer(registry, record_property):
    """Control dependencies must survive even when the answer needs no refund data."""
    model = configured_model()
    if not all((model.base_url, model.api_key, model.model)):
        pytest.skip('Planner LLM service not configured')
    outcome = DynamicPlanner(registry, model).plan(
        '查询订单2025101234，按实际金额申请整单退款，原因是买错了。审核结束后再回答七天无理由退货条件。')
    record_property('planning_result', outcome.model_dump_json())
    assert outcome.plan is not None, outcome.model_dump_json()
    steps = {step.step_id: step for step in outcome.plan.steps}
    refund = next(s for s in steps.values() if s.capability_id == 'm7.refund_approval')
    answer = next(s for s in steps.values() if s.capability_id == 'm1.faq_chat')
    def ancestors(step_id):
        return {dep for dep in steps[step_id].depends_on} | {
            ancestor for dep in steps[step_id].depends_on for ancestor in ancestors(dep)}
    assert refund.step_id in ancestors(answer.step_id), outcome.model_dump_json()
    report = Executor(registry).execute(outcome.plan)
    record_property('mock_execution', report.model_dump_json())
    assert report.steps[refund.step_id].status == 'waiting_approval'
    assert report.steps[answer.step_id].status == 'pending'
