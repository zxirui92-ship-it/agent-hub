"""Different team variable names reach the same services without copying keys."""
import json
import os

import pytest

from common.config_env import resolve_env
from common.model_config import text_config
from agents.router.config import Settings
from hub_platform.planner import configured_model, public_diagnostic
from scripts.check_live_config import check_config


def test_custom_text_names_override_stale_values_without_mutating_environment():
    env = {'LLM_API_KEY_ENV':'TEAM_TOKEN', 'TEAM_TOKEN':'private-example-token',
           'LLM_API_KEY':'stale-token', 'LLM_BASE_URL_ENV':'TEAM_ENDPOINT',
           'TEAM_ENDPOINT':'https://example.test/v1', 'LLM_MODEL_ENV':'TEAM_MODEL',
           'TEAM_MODEL':'team-model'}
    before = dict(env)
    config = text_config(env)
    assert (config.api_key, config.base_url, config.model) == (
        'private-example-token', 'https://example.test/v1', 'team-model')
    assert env == before
    assert 'private-example-token' not in repr(config)


@pytest.mark.parametrize('alias,source', [('MISSING', {}), ('EMPTY', {'EMPTY':'  '}),
                                         ('paste-key-here', {})])
def test_explicit_bad_mapping_cannot_fall_back_to_existing_key(alias, source):
    with pytest.raises(ValueError, match='LLM_API_KEY_ENV') as exc:
        text_config({'LLM_API_KEY':'old-account', 'LLM_API_KEY_ENV':alias, **source})
    assert 'old-account' not in str(exc.value) and alias not in str(exc.value)


def test_alias_partial_group_cannot_borrow_another_providers_key():
    config = text_config({'LLM_MODEL_ENV':'MY_MODEL', 'MY_MODEL':'model',
                          'BAILIAN_API_KEY':'other-account', 'LLM_PROVIDER':'bailian'})
    assert config.source == 'LLM_*' and config.api_key == ''


def test_bailian_mapping_drives_text_search_image_and_planner(monkeypatch):
    monkeypatch.setattr('agents.router.config.load_dotenv', lambda *a, **k: None)
    monkeypatch.setattr('hub_platform.planner.load_dotenv', lambda *a, **k: None)
    env = {'LLM_PROVIDER':'bailian', 'BAILIAN_API_KEY_ENV':'DASHSCOPE_API_KEY',
           'DASHSCOPE_API_KEY':'private-example-token', 'BAILIAN_BASE_URL_ENV':'TEAM_URL',
           'TEAM_URL':'https://example.test/compatible-mode/v1',
           'HUB_PLANNER_MODEL_ENV':'ROUTE_MODEL', 'ROUTE_MODEL':'routing-model'}
    monkeypatch.setattr(os, 'environ', env)
    settings = Settings.from_env()
    assert settings.llm_api_key == settings.search_api_key == settings.image_api_key == env['DASHSCOPE_API_KEY']
    assert settings.search_provider == settings.image_provider == 'bailian'
    assert settings.image_model == 'qwen-image-2.1-pro'
    planner = configured_model()
    assert planner.api_key == settings.llm_api_key and planner.model == 'routing-model'
    status = check_config(env)
    assert all(v['configured'] for v in status['services'].values())
    assert status['network_called'] is False
    assert env['DASHSCOPE_API_KEY'] not in json.dumps(status)
    assert env['TEAM_URL'] not in json.dumps(status)


def test_separate_skill_mappings_do_not_mix_accounts(monkeypatch):
    monkeypatch.setattr('agents.router.config.load_dotenv', lambda *a, **k: None)
    env = {'M4_IMAGE_API_KEY_ENV':'IMAGE_TOKEN', 'IMAGE_TOKEN':'image-only-key',
           'M4_IMAGE_BASE_URL':'https://image.test/v1', 'M4_IMAGE_MODEL':'image-model',
           'M4_SEARCH_API_KEY_ENV':'SEARCH_TOKEN', 'SEARCH_TOKEN':'search-only-key',
           'M4_SEARCH_URL':'https://search.test/search', 'M4_SEARCH_PROVIDER':'tavily',
           'BAILIAN_API_KEY':'another-account', 'BAILIAN_BASE_URL':'https://other.test/v1'}
    monkeypatch.setattr(os, 'environ', env)
    value = Settings.from_env()
    assert value.image_api_key == env['IMAGE_TOKEN'] and value.image_provider == 'openai'
    assert value.search_api_key == env['SEARCH_TOKEN'] and value.search_provider == 'tavily'


def test_text_can_run_without_an_unconfigured_optional_image_alias():
    config = text_config({'LLM_API_KEY':'text-key', 'LLM_BASE_URL':'https://text.test/v1',
                          'LLM_MODEL':'model', 'M4_IMAGE_API_KEY_ENV':'MISSING'})
    assert config.api_key == 'text-key'


def test_aliased_secrets_redacted_from_planner_m5_and_pytest(monkeypatch):
    from agents.multi_agent import _public_message
    from agents.router.agent import public_message
    from tests.conftest import redact_report
    monkeypatch.setenv('LLM_API_KEY_ENV', 'MY_CUSTOM_TOKEN')
    monkeypatch.setenv('MY_CUSTOM_TOKEN', '  private-custom-secret  ')
    for redact in (public_diagnostic, _public_message, public_message, redact_report):
        assert redact('error: private-custom-secret') == 'error: [redacted]'


def test_empty_mapping_keeps_direct_configuration():
    assert resolve_env({'LLM_API_KEY_ENV':' ', 'LLM_API_KEY':'original'})['LLM_API_KEY'] == 'original'


def test_resolution_is_single_level_and_idempotent():
    env = {'LLM_API_KEY_ENV':'BAILIAN_API_KEY', 'BAILIAN_API_KEY':'original',
           'BAILIAN_API_KEY_ENV':'TEAM_TOKEN', 'TEAM_TOKEN':'other'}
    resolved = resolve_env(env)
    assert resolved['LLM_API_KEY'] == 'original'
    assert resolved['BAILIAN_API_KEY'] == 'other'
    assert resolve_env(resolved) == resolved
