"""Real business models, local business facts; explicitly opted in only.

Generated text is recorded for human quality review. Structural success alone
is not evidence of useful recommendations or truthful generated explanations.
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from agents.single_agent import SingleAgent
from agents.react_agent import ReActAgent
from agents.plan_execute import WeeklyReportAgent, load_sample_view
from agents.multi_agent import PromotionAgent
from agents.blackboard import DataFusionModule
from agents.workflow.refund_graph import RefundWorkflow
from agents.router.config import Settings
from agents.router.factory import create_agent
from common.errors import ErrorCode
from common.llm import ChatModel
from common.model_config import text_config
from hub_platform.registry import CapabilityRegistry
from hub_platform.planner import DynamicPlanner, configured_model
from hub_platform.executor import Executor
from hub_platform.schema import validate_data
from tests.contract.test_contracts import request_for

pytestmark = [pytest.mark.live, pytest.mark.business_live]


@pytest.fixture
def model():
    load_dotenv(Path(__file__).resolve().parents[2] / '.env', override=False)
    config = text_config()
    if not all((config.base_url, config.api_key, config.model)):
        pytest.fail('Business live run requires a complete LLM_* or DEEPSEEK_* configuration')
    return ChatModel(config.base_url, config.api_key, config.model,
                     timeout=float(os.getenv('LLM_TIMEOUT_SECONDS') or '120'))



def completed(agent, payload, record_property):
    result = agent.invoke(request_for(agent.manifest.capability_id, payload))
    record_property(agent.manifest.capability_id, result.model_dump_json())
    assert result.status == 'completed', result.model_dump_json()
    validate_data(result.data, agent.manifest.output_schema, ErrorCode.CONTRACT_MISMATCH)
    return result


def test_m1_live_policy_and_memory(model, record_property):
    agent = SingleAgent(model, mode='live')
    first = completed(agent, {'question': '我的昵称是海风，请记住。七天退货有什么条件？'}, record_property)
    second = completed(agent, {'question': '我刚才告诉你的昵称是什么？请说出昵称。',
        'session_id': first.data['session_id']}, record_property)
    assert '海风' in second.data['answer']


@pytest.mark.parametrize('order_id', ['2025101234', 'not-a-real-order'])
def test_m2_live_react(model, order_id, record_property):
    agent = ReActAgent(model, mode='live', max_rounds=3)
    result = agent.invoke(request_for('m2.order_tracking', {'order_id': order_id, 'query': '查询订单及物流'}))
    record_property('m2_result', result.model_dump_json())
    if order_id == 'not-a-real-order':
        assert result.status == 'failed' and result.error.code == ErrorCode.NOT_FOUND
    else:
        assert result.status == 'completed', result.model_dump_json()
        validate_data(result.data, agent.manifest.output_schema, ErrorCode.CONTRACT_MISMATCH)
        assert result.data['order_amount'] == 699.0
        assert set(result.data['actions']) == {'query_order', 'query_logistics'}
        assert len(result.data['actions']) <= 3


def test_m3_live_plan_execute(model, record_property):
    result = completed(WeeklyReportAgent(model, mode='live'),
        {'fused_data': load_sample_view('2026-W41'), 'previous_fused_data': load_sample_view('2026-W40')}, record_property)
    assert len(result.data['steps']) == 4
    assert '12684300.00' in result.data['report_markdown']


def test_m2_live_amount_query_still_completes_contract(model, record_property):
    result = completed(ReActAgent(model, mode='live', max_rounds=3),
        {'order_id': '2025101234', 'query': '查询该订单的订单金额与状态'}, record_property)
    assert set(result.data['actions']) == {'query_order', 'query_logistics'}


def test_m5_live_role_collaboration(model, record_property):
    # model fixture validates configuration; M5 retains its own timeout adapter.
    result = completed(PromotionAgent(), {'goal': '为样例店铺制定下周优惠券试投方案，说明四个角色的分工和取舍。',
        'week': '2026-W42', 'budget_amount': 100000.0, 'fused_data': load_sample_view('2026-W41')}, record_property)
    assert {row['role'] for row in result.data['roles']} == {'product', 'operation', 'data', 'service'}


@pytest.mark.parametrize('case', ['operations', 'refund'])
def test_end_to_end_real_planner_and_business_models(model, case, record_property):
    settings = Settings.from_env()
    if settings.mode != 'live':
        pytest.fail('End-to-end registry requires M4_MODE=live')
    registry = CapabilityRegistry()
    for agent in (SingleAgent(model, mode='live'), ReActAgent(model, mode='live', max_rounds=3),
                  WeeklyReportAgent(model, mode='live'), create_agent(settings), PromotionAgent(),
                  DataFusionModule(), RefundWorkflow()):
        registry.register(agent.manifest, agent)
    goals = {
        'operations': ('融合2026年第41周订单、行为和营销数据，生成周报，再依据周报制定下周大促方案，预算10万元。',
                       {'m6.data_fusion', 'm3.weekly_report', 'm5.promotion_plan'}),
        'refund': ('查询订单2025101234，再按查询得到的订单金额申请整单退款，原因是买错了。',
                   {'m2.order_tracking', 'm7.refund_approval'}),
    }
    goal, expected = goals[case]
    outcome = DynamicPlanner(registry, configured_model(), max_repairs=0).plan(goal)
    record_property('planning_result', outcome.model_dump_json())
    assert outcome.plan is not None, outcome.model_dump_json()
    assert {step.capability_id for step in outcome.plan.steps} == expected
    assert len(outcome.plan.steps) == len(expected)
    report = Executor(registry).execute(outcome.plan)
    record_property('execution_report', report.model_dump_json())
    assert report.status == ('completed' if case == 'operations' else 'waiting_approval'), report.model_dump_json()
    steps = {step.capability_id: step for step in report.steps.values()}
    if case == 'operations':
        assert steps['m3.weekly_report'].inputs['fused_data'] == steps['m6.data_fusion'].result.data['fused_data']
        assert steps['m5.promotion_plan'].inputs['budget_amount'] == 100000.0
        assert steps['m5.promotion_plan'].inputs['report_markdown'] == steps['m3.weekly_report'].result.data['report_markdown']
    else:
        assert steps['m7.refund_approval'].inputs['refund_amount'] == steps['m2.order_tracking'].result.data['order_amount'] == 699.0
        assert steps['m7.refund_approval'].result.continuation_token
