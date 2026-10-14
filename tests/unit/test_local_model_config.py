import pytest
from common.model_config import text_config


def test_local_deepseek_used_without_exporting_generic_credentials():
    env = {'DEEPSEEK_BASE_URL': 'https://example.test', 'DEEPSEEK_API_KEY': 'private-test-key'}
    config = text_config(env)
    assert config.model == 'deepseek-flash' and config.api_key == env['DEEPSEEK_API_KEY']
    assert 'private-test-key' not in repr(config)
    assert 'LLM_API_KEY' not in env


def test_partial_override_never_borrows_keys():
    config = text_config({'LLM_MODEL': 'override', 'DEEPSEEK_API_KEY': 'private-test-key'})
    assert config.api_key == '' and config.base_url == ''


def test_bailian_text_is_separate_from_image_model():
    config = text_config({'LLM_PROVIDER': 'bailian', 'BAILIAN_API_KEY': 'private-test-key',
        'BAILIAN_BASE_URL': 'https://example.test/compatible-mode/v1', 'BAILIAN_IMAGE_MODEL': 'qwen-image-2.0'})
    assert config.model == 'qwen-plus' and config.source == 'BAILIAN_*'


def test_invalid_provider_is_not_silently_ignored():
    with pytest.raises(ValueError):
        text_config({'LLM_PROVIDER': 'unknown'})
