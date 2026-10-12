import base64
from io import BytesIO
import json
import struct
import zlib
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from agents.router.config import Settings
from agents.router.skills.code_gen import CodeGenSkill
from agents.router.skills.image_gen import ImageGenSkill, MOCK_PNG
from agents.router.skills.kb_qa import KbQaSkill
from agents.router.skills.web_search import WebSearchSkill
from common import http_client
from common.errors import ErrorCode, ServiceError
from common.llm import ChatModel
from tests.unit.test_m4_router import FakeModel


def test_search_real_adapter_with_fake_transport():
    calls=[]
    def transport(*args):
        calls.append(args)
        return {'results':[{'title':'Reference','url':'https://example.com/doc','content':'Evidence','score':0.9}]}
    value=json.loads(WebSearchSkill('dummy','https://api.example.com/search',12,transport=transport).run({'query':'question'}))
    assert value['mode']=='live' and value['results'][0]['source_url']=='https://example.com/doc'
    assert calls==[('https://api.example.com/search',{'query':'question','max_results':5},'dummy',12)]
    assert 'score' not in value['results'][0]


@pytest.mark.parametrize('response',[{}, {'results':{}}, {'results':[{}]}, {'results':[{'title':'x','url':'bad','content':'x'}]}])
def test_search_rejects_malformed_response(response):
    with pytest.raises(ServiceError) as exc:
        WebSearchSkill('dummy','https://example.com',transport=lambda *args:response).run({'query':'q'})
    assert exc.value.code==ErrorCode.CONTRACT_MISMATCH


@pytest.mark.parametrize('skill',[WebSearchSkill(),ImageGenSkill(),CodeGenSkill()])
def test_missing_service_configuration_is_explicit(skill):
    with pytest.raises(ServiceError) as exc: skill.run({'query':'q'})
    assert exc.value.code==ErrorCode.TOOL_UNAVAILABLE and not exc.value.retryable
    assert 'not_configured' in str(exc.value)


def test_code_generated_text_and_language_are_not_executed(tmp_path):
    output=tmp_path/'must_not_exist.txt'
    code=f'open({str(output)!r}, "w").write("unsafe")'
    model=FakeModel(json.dumps({'language':'python','code':code}))
    value=json.loads(CodeGenSkill(model).run({'query':'write a script'}))
    assert value=={'mode':'live','language':'python','code':code}
    assert not output.exists() and model.calls[0][1]=='write a script'


@pytest.mark.parametrize('row',[{'url':'https://example.com/supplied.png'}, {'b64_json':MOCK_PNG}])
def test_image_real_adapter_preserves_supplied_resource(row):
    calls=[]
    def transport(*args):calls.append(args);return {'data':[row]}
    value=json.loads(ImageGenSkill('https://api.example.com/v1','dummy','image-model',8,transport=transport).run({'query':'draw a tree'}))
    assert value['mode']=='live' and len(value['images'])==1
    assert calls[0]==('https://api.example.com/v1/images/generations',{'model':'image-model','prompt':'draw a tree','n':1},'dummy',8)
    assert list(value['images'][0].values())==list(row.values())


def test_mock_image_contains_real_test_bytes_not_fake_url():
    value=json.loads(ImageGenSkill(mock=True).run({'query':'draw'}))
    assert value['mode']=='mock'
    raw=base64.b64decode(value['images'][0]['image_base64'])
    assert raw.startswith(b'\x89PNG\r\n\x1a\n')
    offset=8
    while offset<len(raw):
        size=struct.unpack('>I',raw[offset:offset+4])[0]
        chunk=raw[offset+4:offset+8+size]
        assert zlib.crc32(chunk)==struct.unpack('>I',raw[offset+8+size:offset+12+size])[0]
        if chunk[:4]==b'IDAT':assert len(zlib.decompress(chunk[4:]))==3
        offset+=size+12
    assert offset==len(raw)
    assert 'image_url' not in value['images'][0]


@pytest.mark.parametrize('response',[{}, {'data':[]}, {'data':[{}]}, {'data':[{'url':'fake-path.png'}]}, {'data':[{'b64_json':'invalid!'}]}])
def test_image_bad_provider_data_fails(response):
    with pytest.raises(ServiceError) as exc:
        ImageGenSkill('https://example.com','dummy','image-model',transport=lambda *args:response).run({'query':'q'})
    assert exc.value.code==ErrorCode.CONTRACT_MISMATCH


def test_knowledge_answers_only_from_supplied_entries(tmp_path):
    path=tmp_path/'knowledge.json'
    path.write_text(json.dumps([{'entry_id':'leave-policy','title':'请假规则','keywords':['请假'],'content':'请假须提前两天提交申请。'}]),encoding='utf-8')
    value=json.loads(KbQaSkill(path).run({'query':'请假要提前多久？'}))
    assert value['answer']=='请假须提前两天提交申请。' and value['source_kind']=='configured_knowledge'
    assert value['sources'][0]['entry_id']=='leave-policy'
    with pytest.raises(ServiceError) as exc: KbQaSkill(path).run({'query':'天气'})
    assert exc.value.code==ErrorCode.NOT_FOUND
    path.write_text('not json')
    with pytest.raises(ServiceError): KbQaSkill(path).run({'query':'请假'})


def test_chat_adapter_request_and_response():
    calls=[]
    def transport(*args):calls.append(args);return {'choices':[{'message':{'content':'reply'}}]}
    model=ChatModel('https://example.com/v1','dummy','test-model',7,transport)
    assert model.complete('instruction','query')=='reply'
    assert calls[0]==('https://example.com/v1/chat/completions',{'model':'test-model','messages':[{'role':'system','content':'instruction'},{'role':'user','content':'query'}]},'dummy',7)


@pytest.mark.parametrize('response',[{}, {'choices':[]}, {'choices':[{'message':{'content':None}}]}])
def test_chat_response_validation(response):
    model=ChatModel('https://example.com','dummy','model',transport=lambda *args:response)
    with pytest.raises(ServiceError) as exc:model.complete('x','y')
    assert exc.value.code==ErrorCode.CONTRACT_MISMATCH


def test_http_transport_serializes_and_passes_timeout(monkeypatch):
    def open_fake(request,timeout):
        assert request.full_url=='https://example.com/search' and timeout==4
        assert request.get_header('Authorization')=='Bearer dummy'
        assert json.loads(request.data)=={'query':'退款'}
        return BytesIO(b'{"results":[]}')
    monkeypatch.setattr(http_client,'urlopen',open_fake)
    assert http_client.post_json('https://example.com/search',{'query':'退款'},'dummy',4)=={'results':[]}


@pytest.mark.parametrize('error,retryable',[(HTTPError('https://example.com',401,'secret message',{},None),False),
    (HTTPError('https://example.com',429,'secret message',{},None),True), (TimeoutError('secret message'),True), (URLError('secret message'),True)])
def test_http_errors_preserve_category_without_leaking_raw_response(monkeypatch,error,retryable):
    def fail(*args,**kwargs):raise error
    monkeypatch.setattr(http_client,'urlopen',fail)
    with pytest.raises(ServiceError) as exc:http_client.post_json('https://example.com',{},'dummy',1)
    assert exc.value.code==ErrorCode.TOOL_UNAVAILABLE and exc.value.retryable==retryable
    assert 'secret message' not in str(exc.value)


@pytest.mark.parametrize('kwargs',[{'mode':'invalid'}, {'llm_timeout':0}, {'service_timeout':float('nan')}, {'search_url':'ftp://example.com'}])
def test_config_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):Settings(**kwargs)


def test_env_file_does_not_override_explicit_environment(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path/'.env').write_text('M4_MODE=live\nLLM_TIMEOUT_SECONDS=9\n')
    monkeypatch.setenv('M4_MODE','mock')
    monkeypatch.delenv('LLM_TIMEOUT_SECONDS',raising=False)
    settings=Settings.from_env()
    assert settings.mode=='mock' and settings.llm_timeout==9
