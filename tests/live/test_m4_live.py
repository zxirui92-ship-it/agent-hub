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
def test_real_external_skill(settings,name,query):
    needed={'web_search':(settings.search_api_key,settings.search_url),
            'code_gen':(settings.llm_api_key,settings.llm_base_url,settings.llm_model),
            'image_gen':(settings.image_api_key,settings.image_base_url,settings.image_model)}
    if not all(needed[name]):pytest.skip(f'{name} service not configured')
    value=json.loads(create_agent(settings).skills.invoke(name,{'query':query}))
    assert value['mode']=='live'
