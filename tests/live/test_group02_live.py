"""Small, explicit paid-model acceptance set using imported simulation facts."""
import json
from pathlib import Path
import time

import pytest

from agents.single_agent import SingleAgent
from agents.react_agent import ReActAgent
from agents.blackboard import DataFusionModule
from agents.plan_execute import WeeklyReportAgent
from agents.plan_execute import load_sample_view
from agents.multi_agent import PromotionAgent
from agents.router.config import Settings
from agents.router.factory import create_agent
from common.errors import ErrorCode
from common.llm import ChatModel
from common.model_config import text_config
from hub_platform.registry import CapabilityRegistry
from hub_platform.planner import DynamicPlanner, configured_model
from hub_platform.executor import Executor
from tests.contract.test_contracts import request_for

pytestmark = [pytest.mark.live, pytest.mark.business_live]


@pytest.fixture
def configured(monkeypatch, record_property):
    monkeypatch.setenv('HUB_DATA_DIR',str(Path(__file__).resolve().parents[2]/'data/group02'))
    monkeypatch.setenv('M6_DATA_DIR','')
    monkeypatch.setenv('M4_KB_PATH','')
    monkeypatch.setenv('M4_MODE','live')
    config=text_config()
    assert config.api_key and config.base_url and config.model, '缺少完整文本模型配置'
    record_property('model',config.model)
    start=time.perf_counter()
    class CountedModel:
        def __init__(self): self.calls=0
        def complete(self,system,query):
            self.calls+=1
            return ChatModel(config.base_url,config.api_key,config.model,timeout=90).complete(system,query)
    model=CountedModel()
    yield model
    record_property('injected_model_calls',model.calls)
    record_property('elapsed_seconds',round(time.perf_counter()-start,2))


def test_m1_live_greeting_memory_and_policy_conflict(configured,record_property):
    agent=SingleAgent(configured)
    for question in ['你好，我的昵称是海风。','商品保修政策是什么？请引用条目并指出口径差异。',
                     '那小家电到底保修几年？还记得我的昵称吗？']:
        result=agent.invoke(request_for('m1.faq_chat',{'question':question,'session_id':'sess-000000000101'}))
        record_property('m1_answer',result.model_dump_json())
        assert result.status=='completed', result.model_dump_json()
        if question.startswith('你好'):
            assert 'not_found' not in result.data['answer'] and '检索' not in result.data['answer']
    answer=result.data['answer']
    assert '海风' in answer and '1' in answer and '2' in answer
    assert any(w in answer for w in ('确认','冲突','不一致','差异'))


@pytest.mark.parametrize('order_id,expected',[('2025100003','completed'),('2025101234','failed')])
def test_m2_live_good_order_and_source_conflict(configured,record_property,order_id,expected):
    result=ReActAgent(configured).invoke(request_for('m2.order_tracking',{'order_id':order_id}))
    record_property('m2_result',result.model_dump_json())
    assert result.status==expected
    if expected=='completed':
        assert result.data['order_amount']==12900 and result.data['order_status']=='delivered'
        assert set(result.data['actions'])=={'query_order','query_logistics'}
    else:
        assert result.error.code==ErrorCode.CONTRACT_MISMATCH


def test_m4_live_semantic_kb_route(configured,record_property):
    agent=create_agent(Settings.from_env())
    result=agent.invoke(request_for('m4.capability_gateway',{'query':'请查询企业内部知识库中小家电的保修规定，说明不同条目是否一致。'}))
    record_property('m4_result',result.model_dump_json())
    assert result.status=='completed' and result.data['skill_name']=='kb_qa'
    data=json.loads(result.data['result'])
    assert data['source_kind']=='imported_simulation' and data['warnings']


def test_dynamic_two_week_report_and_promotion(configured,record_property):
    registry=CapabilityRegistry()
    for module in [DataFusionModule(),WeeklyReportAgent(configured),PromotionAgent()]:
        registry.register(module.manifest,module)
    planned=DynamicPlanner(registry,configured_model(),max_repairs=1).plan(
        '请分别融合2025-W41和相邻上一周2025-W40的经营数据，基于这两个完整视图生成W41周报，'
        '必须计算周环比；再依据本周视图和周报制定下周大促方案，预算10000元。')
    record_property('plan',planned.model_dump_json())
    assert planned.plan is not None
    report=Executor(registry).execute(planned.plan)
    record_property('report',report.model_dump_json())
    assert report.status=='completed', report.model_dump_json()
    steps=list(report.steps.values())
    weekly=next(s for s in steps if s.capability_id=='m3.weekly_report')
    assert weekly.inputs['previous_fused_data']['week']=='2025-W40'
    assert '-8.91%' in weekly.result.data['report_markdown']
    promotion=next(s for s in steps if s.capability_id=='m5.promotion_plan')
    assert promotion.inputs['budget_amount']==1000000
    assert len(promotion.result.data['roles'])==4


def test_m3_live_sees_both_week_funnels(configured,record_property):
    result=WeeklyReportAgent(configured).invoke(request_for('m3.weekly_report', {
        'fused_data':load_sample_view('2025-W41'), 'previous_fused_data':load_sample_view('2025-W40')}))
    record_property('m3_result',result.model_dump_json())
    assert result.status=='completed'
    report=result.data['report_markdown']
    assert '-8.91%' in report and '498000/287000/118000/71400' in report
    assert '472000/274000/109000/66200' in report
