"""Real model semantics and external services. Disabled unless explicitly opted in."""
import json

import pytest

from agents.router.config import Settings
from agents.router.factory import create_agent

pytestmark=pytest.mark.live


@pytest.fixture
def settings():
    value=Settings.from_env()
    if value.mode!='live':pytest.fail('Live tests require M4_MODE=live')
    return value


@pytest.mark.parametrize('query,expected',[
    ('搜索今天公开报道的电商新闻，给出网页来源','web_search'),
    ('公司的大促优惠券可以叠加吗？查内部知识库','kb_qa'),
    ('用 Python 编写两个整数相加的函数','code_gen'),
    ('画一张蓝色小鸟插画','image_gen'),
    ('替我到办公室浇花','none'),
])
def test_real_model_semantic_routing(settings,query,expected):
    if not all((settings.llm_api_key,settings.llm_base_url,settings.llm_model)):
        pytest.skip('LLM service not configured')
    agent=create_agent(settings)
    decision=agent.router.select(query,agent.skills.list_skills())
    assert decision.skill_name==(None if expected=='none' else expected)
    assert decision.route_reason


@pytest.mark.parametrize('name,query', [('web_search','Python official documentation'),('code_gen','Write Python add(a,b) function'),('image_gen','A simple blue bird icon')])
def test_real_external_skill(settings,name,query,record_property):
    needed={'web_search':(settings.search_api_key,settings.search_url),
            'code_gen':(settings.llm_api_key,settings.llm_base_url,settings.llm_model),
            'image_gen':(settings.image_api_key,settings.image_base_url,settings.image_model)}
    if not all(needed[name]):pytest.skip(f'{name} service not configured')
    value=json.loads(create_agent(settings).skills.invoke(name,{'query':query}))
    record_property('skill_result', json.dumps(value, ensure_ascii=False))
    assert value['mode']=='live'
    if name == 'web_search':
        assert value['results'], 'Search must return actual provider sources'
        assert all(row['source_url'].startswith(('https://', 'http://')) for row in value['results'])


def test_real_search_through_executor(settings, record_property):
    """Paid search + real semantic Router + public platform contract, no forced skill."""
    from hub_platform.executor import Executor
    from hub_platform.registry import CapabilityRegistry
    if not all((settings.search_api_key, settings.search_url, settings.llm_api_key,
                settings.llm_base_url, settings.llm_model)):
        pytest.skip('Search and routing services must both be configured')
    agent = create_agent(settings)
    registry = CapabilityRegistry()
    registry.register(agent.manifest, agent)
    report = Executor(registry).execute({'plan_id': 'plan-20261014-401', 'goal': '国内联网搜索实测',
        'steps': [{'step_id': 's1', 'capability_id': agent.manifest.capability_id,
            'inputs': {'query': {'literal': '请联网搜索阿里云百炼联网搜索的官方使用文档，给出网页来源链接。'}}}]})
    record_property('execution_report', report.model_dump_json())
    assert report.status == 'completed', report.model_dump_json()
    data = report.final_results['s1']
    assert data['skill_name'] == 'web_search' and data['route_reason']
    value = json.loads(data['result'])
    assert value['mode'] == 'live' and value['results']
    assert all(row['source_url'].startswith(('https://', 'http://')) for row in value['results'])
