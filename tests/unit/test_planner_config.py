import os
import pytest
from hub_platform import planner


@pytest.fixture(autouse=True)
def clean_config(monkeypatch):
    monkeypatch.setattr(planner, 'load_dotenv', lambda *args, **kwargs: None)
    for key in ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL', 'DEEPSEEK_BASE_URL',
                'DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL', 'HUB_PLANNER_MODEL', 'LLM_TIMEOUT_SECONDS',
                'LLM_PROVIDER', 'BAILIAN_API_KEY', 'BAILIAN_BASE_URL', 'BAILIAN_TEXT_MODEL'):
        monkeypatch.delenv(key, raising=False)


def test_planner_uses_deepseek_env_without_mutating_business_config(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-only-key')
    model = planner.configured_model()
    assert model.base_url == 'https://api.deepseek.com'
    assert model.api_key == 'test-only-key' and model.model == 'deepseek-flash'
    assert all(not os.getenv(key) for key in ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL'))


def test_explicit_generic_configuration_wins_as_one_group(monkeypatch):
    for key, value in {'LLM_BASE_URL': 'https://example.test/v1', 'LLM_API_KEY': 'generic-test-key',
        'LLM_MODEL': 'custom-model', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com',
        'DEEPSEEK_API_KEY': 'deepseek-test-key'}.items():
        monkeypatch.setenv(key, value)
    model = planner.configured_model()
    assert (model.base_url, model.api_key, model.model) == ('https://example.test/v1', 'generic-test-key', 'custom-model')


def test_partial_generic_configuration_never_borrows_another_providers_key(monkeypatch):
    monkeypatch.setenv('LLM_BASE_URL', 'https://example.test/v1')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'deepseek-test-key')
    model = planner.configured_model()
    assert model.api_key == '' and model.model == ''


def test_planner_model_can_be_overridden_without_changing_module_model(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_MODEL', 'provider-default')
    monkeypatch.setenv('HUB_PLANNER_MODEL', 'planner-override')
    assert planner.configured_model().model == 'planner-override'
    assert os.getenv('DEEPSEEK_MODEL') == 'provider-default'


def test_missing_credentials_remain_missing():
    model = planner.configured_model()
    assert not model.base_url and not model.api_key
