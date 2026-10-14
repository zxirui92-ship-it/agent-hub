import json
from scripts.check_live_config import check_config


def test_preflight_never_emits_config_values():
    env = {'DEEPSEEK_API_KEY': 'secret-test-value', 'DEEPSEEK_BASE_URL': 'private-endpoint'}
    result = check_config(env)
    assert result['services']['planner']['configured']
    assert result['services']['business_llm']['configured']
    assert 'secret-test-value' not in json.dumps(result)
    assert 'private-endpoint' not in json.dumps(result)
    assert result['network_called'] is False


def test_pytest_failure_redaction(monkeypatch):
    from tests.conftest import redact_report
    monkeypatch.setenv('BAILIAN_API_KEY', 'test-secret-value')
    assert redact_report("api_key = 'test-secret-value'; HTTP 403") == "api_key = '[redacted]'; HTTP 403"


def test_partial_llm_config_does_not_claim_planner_fallback():
    result = check_config({'LLM_MODEL': 'chosen-model', 'DEEPSEEK_API_KEY': 'key', 'DEEPSEEK_BASE_URL': 'url'})
    assert not result['services']['planner']['configured']
    assert result['services']['planner']['source'] == 'LLM_*'


def test_whitespace_and_service_groups_remain_independent():
    result = check_config({'M4_SEARCH_URL': 'url', 'M4_SEARCH_API_KEY': 'key', 'LLM_API_KEY': '  '})
    assert result['services']['search']['configured']
    assert not result['services']['image']['configured']
    assert 'DEEPSEEK_API_KEY' in result['services']['business_llm']['missing']


def test_planner_override_does_not_complete_business_configuration():
    result = check_config({'LLM_BASE_URL': 'url', 'LLM_API_KEY': 'key', 'HUB_PLANNER_MODEL': 'planner-only'})
    assert result['services']['planner']['configured']
    assert not result['services']['business_llm']['configured']
