import json
from copy import deepcopy

import pytest

from agents.router.config import Settings
from agents.router.factory import create_agent
from agents.router.skills.bailian_search import BailianSearchSkill, search_url
from common.errors import ErrorCode, ServiceError
from scripts.check_live_config import check_config

BASE = 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
RESPONSE = {'output': {'choices': [{'message': {'content': '检索摘要[ref_1]'}}],
    'search_info': {'search_results': [{'title': '公开文档', 'url': 'https://help.aliyun.com/', 'index': 1}]}}}


def test_native_request_and_actual_source_metadata():
    def transport(url, body, key, timeout):
        assert url == 'https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/text-generation/generation'
        assert body['model'] == 'qwen-plus' and key == 'test-key' and timeout == 60
        assert body['input']['messages'][0]['content'] == '搜索公开文档'
        assert body['parameters']['enable_search'] is True
        assert body['parameters']['search_options']['forced_search'] is True
        assert body['parameters']['search_options']['enable_source'] is True
        return deepcopy(RESPONSE)
    value = json.loads(BailianSearchSkill(BASE, 'test-key', transport=transport).run({'query': '搜索公开文档'}))
    assert value['provider'] == 'bailian' and value['mode'] == 'live'
    assert value['answer'] == '检索摘要[ref_1]'
    assert value['results'] == [{'title': '公开文档', 'source_url': 'https://help.aliyun.com/', 'content': '', 'index': 1}]
    assert value['source_content_available'] is False


@pytest.mark.parametrize('response', [{}, {'output': None},
    {'output': {'choices': [{'message': {'content': '这里有 https://example.com 但并未实际检索'}}]}},
    {'output': {'choices': [], 'search_info': {'search_results': []}}}])
def test_model_answer_without_search_metadata_is_not_success(response):
    with pytest.raises(ServiceError) as caught:
        BailianSearchSkill(BASE, 'key', transport=lambda *args: response).run({'query': 'search'})
    assert caught.value.code == ErrorCode.CONTRACT_MISMATCH


@pytest.mark.parametrize('change', [{'url': 'file:///secret'}, {'url': 'https://u:p@example.com'},
    {'title': None}, {'index': True}, {'url': 7}])
def test_malformed_provider_sources_rejected(change):
    response = deepcopy(RESPONSE)
    response['output']['search_info']['search_results'][0].update(change)
    with pytest.raises(ServiceError) as caught:
        BailianSearchSkill(BASE, 'key', transport=lambda *args: response).run({'query': 'search'})
    assert caught.value.code == ErrorCode.CONTRACT_MISMATCH


def test_no_sources_and_provider_errors_are_failures():
    empty = deepcopy(RESPONSE)
    empty['output']['search_info']['search_results'] = []
    for response in (empty, {'code': 'Failure', 'message': 'private-body'}):
        with pytest.raises(ServiceError) as caught:
            BailianSearchSkill(BASE, 'key', transport=lambda *args: response).run({'query': 'search'})
        assert caught.value.code == ErrorCode.TOOL_UNAVAILABLE
        assert 'private-body' not in str(caught.value)


def test_missing_configuration_mock_and_transport_failure():
    with pytest.raises(ServiceError, match='not_configured'):
        BailianSearchSkill().run({'query': 'search'})
    assert json.loads(BailianSearchSkill(mock=True).run({'query': 'search'}))['mode'] == 'mock'
    failure = ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'HTTP 429', retryable=True)
    def fail(*args):
        raise failure
    with pytest.raises(ServiceError) as caught:
        BailianSearchSkill(BASE, 'key', transport=fail).run({'query': 'search'})
    assert caught.value is failure and caught.value.retryable


@pytest.mark.parametrize('base', ['https://example.com/unknown', 'file:///tmp',
    'https://example.com/?secret=x', 'https://user:password@example.com'])
def test_invalid_endpoint_does_not_send_credentials(base):
    with pytest.raises(ValueError):
        search_url(base)


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    import os
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith(('M4_', 'BAILIAN_', 'LLM_')):
            monkeypatch.delenv(key)
    return monkeypatch


def test_default_domestic_config_factory_and_preflight(clean_env):
    clean_env.setenv('BAILIAN_BASE_URL', BASE)
    clean_env.setenv('BAILIAN_API_KEY', 'secret-test-key')
    value = Settings.from_env()
    assert value.search_provider == 'bailian' and value.search_model == 'qwen-plus'
    assert value.search_url == BASE and value.search_api_key == 'secret-test-key'
    assert 'secret-test-key' not in repr(value)
    import os
    status = check_config(os.environ)['services']['search']
    assert status == {'configured': True, 'missing': [], 'provider': 'bailian', 'source': 'BAILIAN_*'}
    # Factory uses the domestic implementation; mock remains explicitly labelled.
    clean_env.setenv('M4_MODE', 'mock')
    assert json.loads(create_agent().skills.invoke('web_search', {'query': 'search'}))['mode'] == 'mock'


@pytest.mark.parametrize('provider', ['tavily', 'bailian'])
def test_partial_override_never_borrows_bailian_key(clean_env, provider):
    clean_env.setenv('BAILIAN_BASE_URL', BASE)
    clean_env.setenv('BAILIAN_API_KEY', 'must-not-borrow')
    clean_env.setenv('M4_SEARCH_URL', 'https://example.com')
    clean_env.setenv('M4_SEARCH_PROVIDER', provider)
    value = Settings.from_env()
    assert value.search_provider == provider and value.search_api_key == ''
    import os
    assert check_config(os.environ)['services']['search']['missing'] == ['M4_SEARCH_API_KEY']


def test_explicit_tavily_and_invalid_provider(clean_env):
    clean_env.setenv('BAILIAN_API_KEY', 'key')
    clean_env.setenv('M4_SEARCH_PROVIDER', 'tavily')
    assert Settings.from_env().search_api_key == ''
    clean_env.setenv('M4_SEARCH_PROVIDER', 'unknown')
    with pytest.raises(ValueError, match='M4_SEARCH_PROVIDER'):
        Settings.from_env()
