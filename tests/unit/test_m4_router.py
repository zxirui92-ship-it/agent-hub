import json

import pytest

from agents.router.agent import RouterAgent
from agents.router.config import Settings
from agents.router.factory import create_agent
from agents.router.registry import SkillRegistry
from agents.router.routing import LlmRouter, RouteDecision
from common.errors import ErrorCode, ServiceError
from hub_platform.schema import validate_data
from tests.contract.test_contracts import request_for


class FakeModel:
    def __init__(self, response):
        self.response, self.calls = response, []

    def complete(self, system, query):
        self.calls.append((system, query))
        return self.response


def request(query='退款政策'):
    return request_for('m4.capability_gateway', {'query': query})


@pytest.mark.parametrize('name', ['web_search','kb_qa','code_gen','image_gen'])
def test_mock_four_skills_follow_public_manifest(name):
    agent=create_agent(Settings(mode='mock'))
    response=agent.invoke(request(f'{name}: 退款政策'))
    assert response.status=='completed'
    assert response.data['skill_name']==name
    assert 'Mock' in response.data['route_reason']
    validate_data(response.data,agent.manifest.output_schema,ErrorCode.CONTRACT_MISMATCH)
    content=json.loads(response.data['result'])
    assert content['mode']==('local' if name=='kb_qa' else 'mock')


@pytest.mark.parametrize('name', ['web_search','kb_qa','code_gen','image_gen'])
def test_llm_router_structure_with_simulated_responses(name):
    agent=create_agent(Settings(mode='mock'))
    model=FakeModel(json.dumps({'skill_name':name,'route_reason':'测试选择依据'}))
    agent.router=LlmRouter(model)
    response=agent.invoke(request())
    assert response.status=='completed' and response.data['skill_name']==name
    assert len(model.calls)==1
    assert all(skill.name in model.calls[0][0] and skill.description in model.calls[0][0] for skill in agent.skills.list_skills())


def test_fifth_skill_uses_unchanged_router_and_dynamic_catalog():
    agent=create_agent(Settings(mode='mock'))
    model=FakeModel('{"skill_name":"translate_text","route_reason":"翻译能力匹配"}')
    agent.router=LlmRouter(model)
    class TranslateSkill:
        def run(self,payload:dict)->str:
            return 'Test translation: hello'
    agent.skills.register('translate_text','Translate text between languages.',TranslateSkill())
    response=agent.invoke(request('把你好翻译为英语'))
    assert response.status=='completed' and response.data['result']=='Test translation: hello'
    assert 'Translate text between languages.' in model.calls[0][0]
    assert len(agent.skills.list_skills())==5


@pytest.mark.parametrize('output,code',[
    ('{"skill_name":null,"route_reason":"不属于已注册能力"}',ErrorCode.UNKNOWN_CAPABILITY),
    ('{"skill_name":"missing","route_reason":"未知"}',ErrorCode.UNKNOWN_CAPABILITY),
    ('not JSON',ErrorCode.CONTRACT_MISMATCH), ('[]',ErrorCode.CONTRACT_MISMATCH),
    ('{"skill_name":"kb_qa","route_reason":42}',ErrorCode.CONTRACT_MISMATCH),
    ('{"skill_name":"kb_qa","route_reason":""}',ErrorCode.CONTRACT_MISMATCH),
    ('{"skill_name":"kb_qa","route_reason":"ok","private_state":{}}',ErrorCode.CONTRACT_MISMATCH),
])
def test_route_failures_never_dispatch(output,code):
    agent=create_agent(Settings(mode='mock'))
    agent.router=LlmRouter(FakeModel(output))
    class NeverRun:
        def run(self,payload):
            pytest.fail('Invalid route must not invoke a Skill')
    registry=SkillRegistry();registry.register('kb_qa','Knowledge',NeverRun());agent.skills=registry
    response=agent.invoke(request())
    assert response.status=='failed' and response.error.code==code


def test_registry_metadata_query_duplicate_isolation_and_result_contract():
    registry=SkillRegistry()
    class Mutator:
        def run(self,payload):
            payload['nested'].append(2)
            return 'text'
    skill=Mutator();registry.register('test_skill','Description',skill)
    assert registry.get('test_skill') is skill
    assert registry.describe('test_skill').description=='Description'
    before={'nested':[1]}; assert registry.invoke('test_skill',before)=='text'; assert before=={'nested':[1]}
    snapshot=registry.list_skills();snapshot.clear();assert len(registry.list_skills())==1
    with pytest.raises(ServiceError):registry.register('test_skill','again',skill)
    with pytest.raises(ServiceError):registry.get('missing')
    with pytest.raises(ServiceError):registry.register('bad_skill','bad',object())
    with pytest.raises(ValueError):registry.register('bad name','bad',skill)


@pytest.mark.parametrize('behavior,code', [('crash',ErrorCode.INTERNAL_ERROR),('object',ErrorCode.CONTRACT_MISMATCH),('service',ErrorCode.TOOL_UNAVAILABLE)])
def test_skill_failure_retains_error_and_selection(behavior,code,caplog,monkeypatch):
    monkeypatch.setenv('M4_SEARCH_API_KEY','test-secret-key')
    class Broken:
        def run(self,payload):
            if behavior=='crash':raise RuntimeError('test failure test-secret-key')
            if behavior=='service':raise ServiceError(ErrorCode.TOOL_UNAVAILABLE,'service offline')
            return object()
    registry=SkillRegistry();registry.register('broken_skill','Failure fixture',Broken())
    agent=RouterAgent(registry,LlmRouter(FakeModel('{"skill_name":"broken_skill","route_reason":"test selection"}')))
    response=agent.invoke(request())
    assert response.status=='failed' and response.error.code==code
    assert response.data['skill_name']=='broken_skill'
    assert 'test-secret-key' not in response.model_dump_json()+caplog.text
    if behavior=='crash': assert 'RuntimeError: test failure' in response.error.message
    assert response.error.request_id==request().request_id


def test_unconfigured_live_route_does_not_silently_mock():
    response=create_agent(Settings()).invoke(request())
    assert response.status=='failed' and response.error.code==ErrorCode.TOOL_UNAVAILABLE
    assert 'not_configured' in response.error.message and not response.error.retryable


@pytest.mark.parametrize('payload',[{}, {'query':''}, {'query':'  '}, {'query':42}, {'query':'x','extra':1}])
def test_invalid_input_returns_error(payload):
    response=create_agent(Settings(mode='mock')).invoke(request_for('m4.capability_gateway',payload))
    assert response.error.code==ErrorCode.INVALID_INPUT


def test_route_and_completion_logs_are_correlated(caplog):
    import logging
    with caplog.at_level(logging.INFO,logger='agent_hub.m4'):
        response=create_agent(Settings(mode='mock')).invoke(request('kb_qa: 退款'))
    events=[json.loads(record.message) for record in caplog.records]
    assert [e['status'] for e in events]==['running','completed']
    assert all(e['request_id']==response.request_id and e['trace_id']==response.trace_id and e['tool_name']=='kb_qa' for e in events)


def test_invalid_injected_router_and_empty_catalog():
    agent=create_agent(Settings(mode='mock'))
    class InvalidRouter:
        def select(self,*args):return RouteDecision('kb_qa',42)
    agent.router=InvalidRouter()
    assert agent.invoke(request()).error.code==ErrorCode.CONTRACT_MISMATCH
    model=FakeModel('unused')
    agent=RouterAgent(SkillRegistry(),LlmRouter(model))
    assert agent.invoke(request()).error.code==ErrorCode.UNKNOWN_CAPABILITY
    assert model.calls==[]
