"""Replay the observed W43 poster plan without calling paid model services."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from agents.blackboard import DataFusionModule
from agents.router.agent import RouterAgent
from agents.router.registry import SkillRegistry
from agents.router.routing import LlmRouter, RouteDecision
from common.business_data import BusinessData
from common.errors import ErrorCode
from common.weekly_data import load_business_view
from hub_platform.executor import Executor
from hub_platform.planner import DynamicPlanner, PlanningError
from hub_platform.registry import CapabilityRegistry
from tests.contract.test_contracts import request_for
from tests.unit.test_planner import ScriptedModel, ready
from tests.unit.test_m4_router import FakeModel
from common.artifact_intent import image_requested


GOAL = '就2025w43的运营情况，帮我生成一份双十一的成果海报'
OBSERVED_QUERY = ('根据2025-W43运营数据和大促执行方案，生成一份面向管理层的双十一成果海报，'
                  '突出销售额、订单量、转化率提升、私域ROI及关键行动成效。使用Markdown格式输出，适配海报排版。')
DATA = Path(__file__).resolve().parents[2] / 'data/group02'
FACTS = load_business_view(BusinessData(DATA), '2025-W43')


def history():
    return {'history': [{'report': {'steps': {'s1': {'status': 'completed', 'result': {
        'status': 'completed', 'capability_id': 'm6.data_fusion', 'data': {'fused_data': FACTS}}}}}}]}


def poster_step(**extra):
    return {'step_id': 's1', 'capability_id': 'm4.capability_gateway',
            'inputs': {'query': {'literal': OBSERVED_QUERY}, **extra}}


def test_recorded_markdown_plan_is_rejected_before_execution(registry):
    with pytest.raises(PlanningError) as error:
        DynamicPlanner(registry, ScriptedModel(ready([poster_step()])), max_repairs=0).plan(GOAL, context=history())
    assert error.value.code == ErrorCode.INVALID_PLAN


def test_image_contract_cannot_dispatch_recorded_code_route():
    class NeverRun:
        def run(self, payload):
            pytest.fail('A poster image request must never invoke code_gen')
    class RecordedRouter:
        def select(self, query, skills):
            return RouteDecision('code_gen', '需生成Markdown格式的成果海报，属于代码生成任务。')
    skills = SkillRegistry()
    skills.register('code_gen', 'Generate source code', NeverRun())
    skills.register('image_gen', 'Generate images', NeverRun())
    result = RouterAgent(skills, RecordedRouter()).invoke(request_for('m4.capability_gateway', {
        'query': OBSERVED_QUERY, 'output_kind': 'image', 'fused_data': FACTS}))
    assert result.status == 'failed'
    assert result.error.code == ErrorCode.CONTRACT_MISMATCH


def test_repaired_plan_reuses_verified_history_and_delivers_facts_to_image_skill():
    calls = []
    class Image:
        def run(self, payload):
            calls.append(payload)
            return json.dumps({'mode': 'test', 'images': [{'image_url': 'https://example.invalid/poster.png'}]})
    skills = SkillRegistry()
    skills.register('image_gen', 'Generate image', Image())
    route_model = FakeModel(json.dumps({'skill_name': 'image_gen', 'route_reason': '用户要求图片海报'}))
    module = RouterAgent(skills, LlmRouter(route_model))
    registry = CapabilityRegistry()
    registry.register(module.manifest, module)
    fixed = poster_step(output_kind={'literal': 'image'}, fused_data={'literal': FACTS})
    fixed['inputs']['query'] = {'literal': GOAL}
    model = ScriptedModel(ready([poster_step()]), ready([fixed]))
    planned = DynamicPlanner(registry, model).plan(GOAL, context=history())
    assert [a.status for a in planned.attempts] == ['invalid', 'accepted']
    result = Executor(registry).execute(planned.plan)
    assert result.status == 'completed', result.model_dump_json()
    assert calls[0]['query'] == GOAL
    assert calls[0]['fused_data'] == FACTS



@pytest.mark.parametrize('mutation', ['missing', 'invented', 'wrong_week', 'failed_history'])
def test_image_plan_cannot_replace_verified_facts_with_invented_metrics(registry, mutation):
    facts = deepcopy(FACTS)
    context = history()
    extra = {'output_kind': {'literal': 'image'}}
    if mutation == 'invented':
        facts['revenue_amount'] = 412000000.0
    if mutation == 'wrong_week':
        facts['week'] = '2025-W42'
    if mutation == 'failed_history':
        context['history'][0]['report']['steps']['s1']['status'] = 'failed'
    if mutation != 'missing':
        extra['fused_data'] = {'literal': facts}
    with pytest.raises(PlanningError):
        step = poster_step(**extra)
        step['inputs']['query'] = {'literal': GOAL}
        DynamicPlanner(registry, ScriptedModel(ready([step])), max_repairs=0).plan(GOAL, context=context)


def test_new_conversation_can_bind_actual_m6_output_to_poster(registry):
    m6 = DataFusionModule(source=BusinessData(DATA))
    registry_with_data = CapabilityRegistry()
    for manifest in registry.list_capabilities():
        module = m6 if manifest.capability_id == 'm6.data_fusion' else registry.get(manifest.capability_id)
        registry_with_data.register(module.manifest, module)
    image = poster_step(output_kind={'literal': 'image'}, fused_data={'ref': 's1.data.fused_data'})
    image['step_id'] = 's2'
    image['inputs']['query'] = {'literal': GOAL}
    image['depends_on'] = ['s1']
    steps = [{'step_id': 's1', 'capability_id': 'm6.data_fusion',
              'inputs': {'week': {'literal': '2025-W43'}}}, image]
    result = DynamicPlanner(registry_with_data, ScriptedModel(ready(steps))).plan(GOAL)
    assert result.plan is not None


@pytest.mark.parametrize('query,expected', [
    ('帮我把 W43 的经营结果做成海报', True),
    ('生成一张双十一战报图片', True),
    ('用Python写一段生成海报的代码', False),
    ('只写海报文案，暂时不要出图', False),
    ('给我海报的Markdown模板', False),
    ('生成海报图片，不要代码，不要Markdown', True),
])
def test_image_requirement_does_not_override_explicit_text_or_source_requests(query, expected):
    assert image_requested(query) is expected


def test_image_skill_text_response_is_not_reported_as_completed():
    class TextOnly:
        def run(self, payload):
            return json.dumps({'language': 'Markdown', 'code': '# fake poster'})
    skills = SkillRegistry()
    skills.register('image_gen', 'Generate images', TextOnly())
    module = RouterAgent(skills, LlmRouter(FakeModel('{"skill_name":"image_gen","route_reason":"image"}')))
    result = module.invoke(request_for('m4.capability_gateway', {'query': GOAL, 'output_kind': 'image', 'fused_data': FACTS}))
    assert result.status == 'failed' and result.error.code == ErrorCode.CONTRACT_MISMATCH


def test_generic_dated_poster_does_not_require_business_metrics(registry):
    goal = '帮我制作2025-W43技术交流会海报'
    step = poster_step(output_kind={'literal': 'image'})
    step['inputs']['query'] = {'literal': goal}
    assert DynamicPlanner(registry, ScriptedModel(ready([step]))).plan(goal).plan is not None


def test_image_requirement_allows_other_gateway_steps_in_same_plan(registry):
    image = poster_step(output_kind={'literal': 'image'}, fused_data={'literal': FACTS})
    image['inputs']['query'] = {'literal': GOAL}
    search = {'step_id': 's2', 'capability_id': 'm4.capability_gateway',
              'inputs': {'query': {'literal': '搜索海报设计灵感'}}}
    assert DynamicPlanner(registry, ScriptedModel(ready([image, search]))).plan(GOAL, context=history()).plan is not None
