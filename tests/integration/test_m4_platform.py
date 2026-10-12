import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agents.router.config import Settings
from agents.router.factory import create_agent
from agents.router.routing import LlmRouter
from common.errors import ErrorCode
from hub_platform.executor import Executor
from hub_platform.registry import CapabilityRegistry
from tests.contract.test_contracts import SAMPLES
from tests.mocks.agents import MOCK_TYPES
from tests.unit.test_m4_router import FakeModel


def real_registry():
    m4=create_agent(Settings(mode='mock'))
    # Real RouterAgent + real LlmRouter control flow, simulated model and offline services.
    m4.router=LlmRouter(FakeModel('{"skill_name":"kb_qa","route_reason":"测试模型选择企业政策知识库"}'))
    registry=CapabilityRegistry()
    for cls in MOCK_TYPES:
        module=m4 if cls.manifest.capability_id==m4.manifest.capability_id else cls()
        registry.register(module.manifest,module)
    return registry


@pytest.mark.parametrize('cls,payload',list(zip(MOCK_TYPES,SAMPLES)))
def test_real_m4_replaces_mock_and_all_seven_execute(cls,payload):
    registry=real_registry()
    assert len(registry.list_capabilities())==7
    plan={'plan_id':'plan-20261012-101','goal':'independent module test','steps':[
        {'step_id':'s1','capability_id':cls.manifest.capability_id,'inputs':{k:{'literal':v} for k,v in payload.items()}}]}
    report=Executor(registry).execute(plan)
    assert report.status=='completed',report.model_dump_json()
    if cls.manifest.capability_id=='m4.capability_gateway':
        assert json.loads(report.final_results['s1']['result'])['mode']=='local'


@pytest.mark.parametrize('name,status',[('operations','completed'),('refund_waiting','waiting_approval'),('failure','failed')])
def test_existing_cross_module_plans_with_real_m4(name,status,load_plan):
    plan=load_plan(name)
    plan['steps'].append({'step_id':'s8','capability_id':'m4.capability_gateway','inputs':{'query':{'literal':'优惠政策'}}})
    report=Executor(real_registry()).execute(plan)
    assert report.status==status
    assert report.steps['s8'].status=='completed'
    if name=='refund_waiting':assert report.steps['s2'].status=='waiting_approval'
    if name=='failure':assert report.steps['s2'].status=='skipped'


def test_real_m4_failure_blocks_downstream_but_other_branch_runs():
    registry=real_registry()
    registry.get('m4.capability_gateway').router=LlmRouter(FakeModel('{"skill_name":null,"route_reason":"no match"}'))
    plan={'plan_id':'plan-20261012-102','goal':'failure propagation','steps':[
        {'step_id':'s1','capability_id':'m4.capability_gateway','inputs':{'query':{'literal':'unknown'}}},
        {'step_id':'s2','capability_id':'m1.faq_chat','depends_on':['s1'],'inputs':{'question':{'ref':'s1.data.result'}}},
        {'step_id':'s3','capability_id':'m1.faq_chat','inputs':{'question':{'literal':'退货'}}}]}
    report=Executor(registry).execute(plan)
    assert report.steps['s1'].error.code==ErrorCode.UNKNOWN_CAPABILITY
    assert report.steps['s2'].status=='skipped' and report.steps['s3'].status=='completed'


def cli(*args,mode='mock'):
    env={k:v for k,v in os.environ.items() if not k.startswith(('LLM_','M4_'))}
    # Empty explicit values prevent dotenv from enabling paid services in subprocesses.
    for key in ('LLM_API_KEY','LLM_BASE_URL','LLM_MODEL','M4_SEARCH_API_KEY','M4_SEARCH_URL',
                'M4_IMAGE_API_KEY','M4_IMAGE_BASE_URL','M4_IMAGE_MODEL','M4_KB_PATH'):
        env[key]=''
    env['M4_MODE']=mode
    return subprocess.run([sys.executable,'-m','agents.router',*args],cwd=Path(__file__).resolve().parents[2],
        env=env,text=True,encoding='utf-8',capture_output=True,check=False)


@pytest.mark.parametrize('query,code',[('web_search: current news',0),('kb_qa: 退款政策',0),('code_gen: write Python',0),('image_gen: draw a tree',0),('unknown request',1)])
def test_standalone_mock_cli(query,code):
    run=cli(query)
    assert run.returncode==code,run.stderr
    value=json.loads(run.stdout)
    assert value['status']==('completed' if code==0 else 'failed')


def test_standalone_list_explicit_kb_and_unconfigured_service():
    run=cli('--list-skills');assert run.returncode==0 and len(json.loads(run.stdout))==4
    run=cli('--skill','kb_qa','退款政策',mode='live');assert run.returncode==0
    run=cli('--skill','web_search','latest news',mode='live');assert run.returncode==1
    assert 'not_configured' in json.loads(run.stdout)['error']['message']
    run=cli('--skill','unknown_skill','request')
    assert run.returncode==1 and json.loads(run.stdout)['error']['code']=='UNKNOWN_CAPABILITY'


def test_platform_cli_replaces_only_m4():
    env={k:v for k,v in os.environ.items() if not k.startswith(('LLM_','M4_'))}
    env['M4_MODE']='mock'
    run=subprocess.run([sys.executable,'-m','hub_platform','tests/fixtures/m4_gateway.json','--real-m4','--json'],
        cwd=Path(__file__).resolve().parents[2],env=env,capture_output=True,text=True,encoding='utf-8',check=False)
    assert run.returncode==0,run.stderr
    value=json.loads(run.stdout)
    assert value['steps']['s1']['result']['data']['route_reason'].startswith('Mock route')
    assert value['steps']['s2']['inputs']['question']==value['steps']['s1']['result']['data']['result']
