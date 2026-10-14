import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import agents.multi_agent as m5
from agents.router.config import Settings
from agents.router.factory import create_agent
from common.errors import ErrorCode, ServiceError
from hub_platform import cli
from hub_platform.executor import Executor
from hub_platform.registry import CapabilityRegistry
from tests.mocks.agents import MOCK_TYPES
from tests.unit.test_m5_multi_agent import FakeLLM


def replacement_registry(model):
    registry = CapabilityRegistry()
    for cls in MOCK_TYPES:
        module = m5.PromotionAgent(model) if cls.manifest.capability_id == m5.M5_CAPABILITY_ID else cls()
        registry.register(module.manifest, module)
    return registry


def test_same_plan_runs_with_real_m5_and_mock(registry, load_plan, caplog):
    caplog.set_level('INFO', logger='agent_hub.m5')
    plan = load_plan('operations')
    fake = FakeLLM()
    mock_result = Executor(registry).execute(plan)
    real = replacement_registry(fake)
    response = Executor(real).execute(plan)
    assert mock_result.status == response.status == 'completed'
    assert real.get_manifest(m5.M5_CAPABILITY_ID) == registry.get_manifest(m5.M5_CAPABILITY_ID)
    inputs = response.steps['s3'].inputs
    assert inputs['report_markdown'] == response.steps['s2'].result.data['report_markdown']
    assert inputs['fused_data'] == response.steps['s1'].result.data['fused_data']
    assert len(fake.prompts) == 5
    assert all('2026-W41' in prompt and '转化率环比下降' in prompt for prompt in fake.prompts[:4])
    assert all('融合数据摘要' in prompt for prompt in fake.prompts[:4])
    assert len(response.final_results['s3']['roles']) == 4
    events = [json.loads(record.message) for record in caplog.records]
    assert len(events) == 10  # Four dispatch/return pairs plus aggregation start/end.
    assert all(event['trace_id'] == response.trace_id and event['task_id'] == response.task_id
               and event['request_id'] == response.steps['s3'].request_id for event in events)


def test_m5_failure_skips_dependents_and_preserves_independent_work(load_plan):
    def model(*args, **kwargs):
        raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, 'offline')
    plan = load_plan('operations')
    plan['steps'] += [
        {'step_id': 's4', 'capability_id': 'm1.faq_chat', 'depends_on': ['s3'],
         'inputs': {'question': {'ref': 's3.data.plan_markdown'}}},
        {'step_id': 's5', 'capability_id': 'm4.capability_gateway',
         'inputs': {'query': {'literal': '退款政策'}}},
    ]
    response = Executor(replacement_registry(model)).execute(plan)
    assert response.status == 'failed'
    assert response.steps['s3'].error.code == ErrorCode.TOOL_UNAVAILABLE
    assert response.steps['s4'].status == 'skipped'
    assert response.steps['s5'].status == 'completed'


def test_platform_cli_can_select_real_m4_and_m5_together(monkeypatch, capsys):
    fake = FakeLLM()
    monkeypatch.setenv('M4_MODE', 'mock')
    monkeypatch.setattr(m5, '_chat', fake)
    assert cli.main(['tests/fixtures/operations.json', '--real-m4', '--real-m5', '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(fake.prompts) == 5 and report['status'] == 'completed'
    assert cli.main(['--list-capabilities', '--real-m4', '--real-m5']) == 0
    manifests = json.loads(capsys.readouterr().out)
    assert len(manifests) == 7
    assert next(item for item in manifests if item['capability_id'] == m5.M5_CAPABILITY_ID)['version'] == '2.0'


def test_m4_and_m5_execute_in_one_registry(load_plan):
    registry = CapabilityRegistry()
    m4, m5_module = create_agent(Settings(mode='mock')), m5.PromotionAgent(FakeLLM())
    for cls in MOCK_TYPES:
        modules = {m4.manifest.capability_id: m4, m5_module.manifest.capability_id: m5_module}
        module = modules.get(cls.manifest.capability_id) or cls()
        registry.register(module.manifest, module)
    plan = load_plan('operations')
    plan['steps'].append({'step_id': 's4', 'capability_id': m4.manifest.capability_id,
                          'inputs': {'query': {'literal': 'kb_qa: 退款政策'}}})
    response = Executor(registry).execute(plan)
    assert response.status == 'completed' and set(response.final_results) == {'s3', 's4'}
    assert json.loads(response.final_results['s4']['result'])['mode'] == 'local'


@pytest.mark.parametrize('entry', [['-m', 'agents.multi_agent'], ['agents/multi_agent.py']])
def test_standalone_manifest_and_missing_configuration(entry):
    env = dict(os.environ)
    for key in ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL', 'DEEPSEEK_API_KEY', 'BAILIAN_API_KEY'):
        env[key] = ''  # Explicit empties prevent dotenv from enabling a real call.
    for key in ('LLM_TIMEOUT_SECONDS', 'M5_TIMEOUT_SECONDS'):
        env[key] = '1'
    cwd = Path(__file__).resolve().parents[2]
    manifest = subprocess.run([sys.executable, *entry, '--manifest'], cwd=cwd, env=env,
                              capture_output=True, text=True, encoding='utf-8')
    assert manifest.returncode == 0, manifest.stderr
    assert json.loads(manifest.stdout)['version'] == '2.0'
    run = subprocess.run([sys.executable, *entry, '本地接口测试'], cwd=cwd, env=env,
                         capture_output=True, text=True, encoding='utf-8')
    assert run.returncode == 1, run.stderr
    result = json.loads(run.stdout)
    assert result['error']['code'] == 'TOOL_UNAVAILABLE'
    assert 'not_configured' in result['error']['message']
    assert not result['error']['retryable'] and result['data'] == {}
