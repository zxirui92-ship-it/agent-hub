"""Replay provider formatting at the real M4 route/skill boundaries."""
import json

import pytest

from agents.router.config import Settings
from agents.router.factory import create_agent
from agents.router.routing import LlmRouter
from agents.router.skills.code_gen import CodeGenSkill
from common.errors import ErrorCode, ServiceError
from tests.unit.test_m4_router import FakeModel, request


@pytest.mark.parametrize('skill', ['web_search', 'code_gen'])
def test_fenced_router_response_reaches_selected_skill(skill):
    agent = create_agent(Settings(mode='mock'))
    agent.router = LlmRouter(FakeModel('```json\n' + json.dumps({
        'skill_name': skill, 'route_reason': 'Matches the requested capability'}) + '\n```'))
    result = agent.invoke(request('用 Python 编写一个两数相加的函数。'))
    assert result.status == 'completed', result.error
    assert result.data['skill_name'] == skill


def test_fenced_code_response_preserves_code():
    code = 'def add(a, b):\n    return a + b\n'
    result = CodeGenSkill(FakeModel('```json\n' + json.dumps({
        'language': 'python', 'code': code}) + '\n```')).run({'query': '两数相加'})
    assert json.loads(result)['code'] == code


def test_m4_requests_structured_json_for_routing_and_code():
    agent = create_agent(Settings(mode='live'))
    assert agent.router.model.json_mode is True
    assert agent.skills.get('code_gen').model.json_mode is True


class SequenceModel:
    def __init__(self, *responses):
        self.responses, self.calls = iter(responses), []

    def complete(self, system, query):
        self.calls.append((system, query))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_router_repairs_fields_before_single_skill_dispatch():
    agent = create_agent(Settings(mode='mock'))
    model = SequenceModel('{"skill_name":42}', '{"skill_name":"code_gen","route_reason":"生成代码"}')
    agent.router = LlmRouter(model)
    result = agent.invoke(request())
    assert result.status == 'completed'
    assert len(model.calls) == 2
    assert 'validation_error' in json.loads(model.calls[1][1])


def test_code_repairs_invalid_json_and_returns_complete_source():
    model = SequenceModel('Here is the code: ```python\nreturn 1\n```',
        json.dumps({'language':'python','code':'def add(a, b):\n    return a + b\n'}))
    result = json.loads(CodeGenSkill(model).run({'query':'写两数相加'}))
    assert result['mode'] == 'live' and result['code'].endswith('return a + b\n')
    assert len(model.calls) == 2


@pytest.mark.parametrize('invalid', ['{}', '[]', '{"code":"truncated',
    'prose\n```json\n{"language":"python","code":"pass"}\n```',
    '```json\n{"language":"python","code":"pass"}\n``` trailing',
    '{"language":"python","code":42}'])
def test_bad_outputs_stop_after_one_repair(invalid):
    model = SequenceModel(invalid, invalid)
    with pytest.raises(ServiceError) as exc:
        CodeGenSkill(model).run({'query':'写代码'})
    assert exc.value.code == ErrorCode.CONTRACT_MISMATCH
    assert '已尝试 2 次' in str(exc.value) and len(model.calls) == 2


def test_authentication_error_does_not_retry_or_fallback():
    model = SequenceModel(ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'HTTP 403', retryable=False))
    with pytest.raises(ServiceError, match='403'):
        CodeGenSkill(model).run({'query':'写代码'})
    assert len(model.calls) == 1
