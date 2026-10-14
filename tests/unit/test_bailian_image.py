import json
import pytest
from agents.router.skills.bailian_image import BailianImageSkill, generation_url
from agents.router.config import Settings
from common.errors import ServiceError, ErrorCode


def test_sync_image_native_request_and_actual_resource():
    calls = []
    def transport(*args):
        calls.append(args)
        return {'output': {'choices': [{'message': {'content': [{'image': 'https://example.test/generated.png'}]}}]}}
    result = json.loads(BailianImageSkill('https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
        'private-test-key', transport=transport).run({'query': 'blue bird'}))
    assert result['images'] == [{'image_url': 'https://example.test/generated.png'}]
    assert calls[0][0].endswith('/api/v1/services/aigc/multimodal-generation/generation')
    assert calls[0][1]['input']['messages'][0]['content'] == [{'text': 'blue bird'}]
    assert calls[0][1]['parameters']['n'] == 1 and result['mode'] == 'live'


@pytest.mark.parametrize('response', [{}, {'output': {'choices': []}},
    {'output': {'choices': [{'message': {'content': [{'image': 'not-a-url'}]}}]}},
    {'output': {'choices': [{'message': {'content': [{'text': 'no image'}]}}]}}])
def test_invalid_response_cannot_be_success(response):
    with pytest.raises(ServiceError) as exc:
        BailianImageSkill('https://example.test', 'key', transport=lambda *args: response).run({'query': 'q'})
    assert exc.value.code == ErrorCode.CONTRACT_MISMATCH


def test_missing_credentials_and_provider_error():
    with pytest.raises(ServiceError) as exc:
        BailianImageSkill().run({'query': 'q'})
    assert exc.value.code == ErrorCode.TOOL_UNAVAILABLE
    with pytest.raises(ServiceError) as exc:
        BailianImageSkill('https://example.test', 'key', transport=lambda *args: {
            'code': 'InvalidParameter', 'message': 'private response'}).run({'query': 'q'})
    assert 'private response' not in str(exc.value)


@pytest.mark.parametrize('url', ['https://example.test/wrong', 'ftp://example.test', 'https://example.test?key=secret'])
def test_endpoint_validation(url):
    with pytest.raises(ValueError):
        generation_url(url)


def test_env_selects_bailian_and_explicit_image_group_stays_isolated(monkeypatch):
    for key in ('M4_IMAGE_PROVIDER', 'M4_IMAGE_BASE_URL', 'M4_IMAGE_API_KEY', 'M4_IMAGE_MODEL'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('BAILIAN_API_KEY', 'private-test-key')
    monkeypatch.setenv('BAILIAN_BASE_URL', 'https://example.test/compatible-mode/v1')
    settings = Settings.from_env()
    assert settings.image_provider == 'bailian' and settings.image_model == 'qwen-image-2.0'
    monkeypatch.setenv('M4_IMAGE_BASE_URL', 'https://other.test/v1')
    settings = Settings.from_env()
    assert settings.image_provider == 'openai' and settings.image_api_key == ''
