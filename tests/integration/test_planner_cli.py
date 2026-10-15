import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import agents.multi_agent as m5
from hub_platform import cli, planner
from tests.unit.test_m5_multi_agent import FakeLLM
from tests.unit.test_planner import ScriptedModel, order_steps, ready


def test_goal_entry_executes_generated_plan(monkeypatch, capsys):
    model = ScriptedModel(ready(order_steps()))
    monkeypatch.setattr(planner, 'configured_model', lambda: model)
    assert cli.main(['--goal', '查询订单2025101234', '--json']) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['status'] == 'completed'
    assert value['plan']['steps'][0]['capability_id'] == 'm2.order_tracking'
    assert value['report']['steps']['s1']['result']['data']['order_amount'] == 699.0


def test_plan_only_prints_plan_without_report(monkeypatch, capsys):
    monkeypatch.setattr(planner, 'configured_model', lambda: ScriptedModel(ready(order_steps())))
    assert cli.main(['--goal', '查订单2025101234', '--plan-only', '--json']) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['status'] == 'ready' and value['report'] is None


@pytest.mark.parametrize('status,exit_code', [('needs_clarification', 4), ('unsupported', 2)])
def test_non_executable_cli_statuses(monkeypatch, capsys, status, exit_code):
    monkeypatch.setattr(planner, 'configured_model', lambda: ScriptedModel({'status': status, 'message': '需要处理'}))
    assert cli.main(['--goal', '任务', '--json']) == exit_code
    value = json.loads(capsys.readouterr().out)
    assert value['status'] == status and value['report'] is None


def test_chat_clarification_and_context_commands(monkeypatch, capsys):
    model = ScriptedModel({'status': 'needs_clarification', 'message': '订单号？'}, ready(order_steps()))
    monkeypatch.setattr(planner, 'configured_model', lambda: model)
    inputs = iter(['帮我查订单', '2025101234', '/context', '/new', '/reset', '/context', '/exit'])
    monkeypatch.setattr('builtins.input', lambda: next(inputs))
    assert cli.main(['--chat', '--json']) == 0
    values = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert values[0]['status'] == 'needs_clarification' and values[1]['status'] == 'completed'
    assert values[0]['task_id'] == values[1]['task_id']
    assert values[2]['active_task']['report']['status'] == 'completed'
    assert values[3]['active_task'] is None and values[3]['history'] == []
    assert values[2]['session_id'] != values[3]['session_id']


def test_goal_real_m5_switch_uses_existing_assembly(monkeypatch, capsys, load_plan):
    monkeypatch.setattr(planner, 'configured_model', lambda: ScriptedModel(ready(load_plan('operations')['steps'])))
    model = FakeLLM()
    monkeypatch.setattr(m5, '_chat', model)
    assert cli.main(['--goal', '分析第41周经营并制定大促方案', '--real-m5', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'completed'
    assert len(model.prompts) == 5


@pytest.mark.parametrize('args', [[], ['--goal', 'x', '--chat'], ['--list-capabilities', '--goal', 'x'],
                                  ['tests/fixtures/operations.json', '--goal', 'x'],
                                  ['--list-capabilities', '--plan-only']])
def test_ambiguous_cli_inputs_rejected(args):
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2


def test_missing_llm_config_is_explicit_in_real_cli():
    env = dict(os.environ)
    for key in ('LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL', 'DEEPSEEK_API_KEY', 'DEEPSEEK_BASE_URL', 'DEEPSEEK_MODEL', 'HUB_PLANNER_MODEL'):
        env[key] = ''
    env['LLM_TIMEOUT_SECONDS'] = '120'
    run = subprocess.run([sys.executable, '-m', 'hub_platform', '--goal', '查订单2025101234', '--json'],
                         cwd=Path(__file__).resolve().parents[2], env=env,
                         capture_output=True, text=True, encoding='utf-8')
    assert run.returncode == 1, run.stderr
    value = json.loads(run.stdout)
    assert value['error']['code'] == 'TOOL_UNAVAILABLE'
    assert 'not_configured' in value['error']['message']
    assert value['report'] is None and len(value['planning_attempts']) == 1


def test_human_report_shows_plan_and_actual_execution(monkeypatch, capsys):
    monkeypatch.setattr(planner, 'configured_model', lambda: ScriptedModel(ready(order_steps())))
    assert cli.main(['--goal', '查订单2025101234']) == 0
    text = capsys.readouterr().out
    assert all(item in text for item in ('生成的计划', '实际执行', 'm2.order_tracking', '执行轨迹'))
