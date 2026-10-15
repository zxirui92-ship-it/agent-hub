import json
import subprocess
import sys

import pytest

from agents.plan_execute import WeeklyReportAgent
from agents.workflow.refund_graph import RefundWorkflow
from agents.multi_agent import PromotionAgent
from agents.router.config import Settings
from agents.router.factory import create_agent
from hub_platform import cli
from hub_platform.executor import Executor
from hub_platform.registry import CapabilityRegistry
from hub_platform.conversation import Conversation
from hub_platform.planner import DynamicPlanner
from tests.mocks.agents import MOCK_TYPES, WeeklyReportMock, RefundApprovalMock
from tests.unit.test_m5_multi_agent import FakeLLM
from tests.unit.test_planner import ScriptedModel, ready


def replacement_registry(*modules):
    by_id = {module.manifest.capability_id: module for module in modules}
    registry = CapabilityRegistry()
    for cls in MOCK_TYPES:
        module = by_id.get(cls.manifest.capability_id) or cls()
        registry.register(module.manifest, module)
    return registry


def test_mock_and_real_share_contracts():
    assert WeeklyReportAgent.manifest == WeeklyReportMock.manifest
    real, mock = RefundWorkflow.manifest, RefundApprovalMock.manifest
    assert real.model_copy(update={'supports_resume': False}) == mock


@pytest.mark.parametrize('module,payload', [
    (WeeklyReportAgent(mode='local'), {'fused_data': {'week': '2026-W41', 'revenue_amount': 1.0,
        'order_count': 1, 'conversion_rate': 0.1, 'anomaly': '无'}}),
    (RefundWorkflow(), {'order_id': 'order-low', 'refund_amount': 199.0, 'reason': '退货'})])
def test_module_logs_keep_top_level_correlation(module, payload, caplog):
    from tests.contract.test_contracts import request_for
    request = request_for(module.manifest.capability_id, payload)
    request.context['trace_id'] = 'conflicting-context-value'
    caplog.set_level('INFO')
    result = module.invoke(request)
    assert result.status == 'completed'
    event = json.loads(caplog.records[-1].message)
    assert event['trace_id'] == request.trace_id and event['task_id'] == request.task_id
    assert event['request_id'] == request.request_id and event['module'] == request.capability_id[:2]


def test_operations_chain_m6_mock_real_m3_real_m5(load_plan):
    llm = FakeLLM()
    registry = replacement_registry(WeeklyReportAgent(mode='local'), PromotionAgent(llm), RefundWorkflow())
    report = Executor(registry).execute(load_plan('operations'))
    assert report.status == 'completed'
    assert report.steps['s2'].inputs['fused_data'] == report.steps['s1'].result.data['fused_data']
    assert report.steps['s3'].inputs['report_markdown'] == report.steps['s2'].result.data['report_markdown']
    assert all(step['status'] == 'completed' for step in report.steps['s2'].result.data['steps'])
    assert len(llm.prompts) == 5 and '120000.00' in llm.prompts[0]


def test_real_refund_wait_keeps_descendants_pending_and_independent_steps_run(load_plan):
    registry = replacement_registry(RefundWorkflow())
    plan = load_plan('refund_waiting')
    plan['steps'] += [
        {'step_id': 's3', 'capability_id': 'm1.faq_chat', 'depends_on': ['s2'], 'inputs': {'question': {'literal': '售后政策'}}},
        {'step_id': 's4', 'capability_id': 'm1.faq_chat', 'inputs': {'question': {'literal': '售后政策'}}}]
    report = Executor(registry).execute(plan)
    assert report.status == 'waiting_approval'
    assert report.steps['s2'].inputs['refund_amount'] == report.steps['s1'].result.data['order_amount']
    assert report.steps['s2'].result.continuation_token
    assert report.steps['s3'].status == 'pending' and report.steps['s4'].status == 'completed'


def test_dynamic_planner_discovers_all_replacements_and_context(load_plan):
    modules = [WeeklyReportAgent(mode='local'), RefundWorkflow(), PromotionAgent(FakeLLM()), create_agent(Settings(mode='mock'))]
    registry = replacement_registry(*modules)
    model = ScriptedModel(ready(load_plan('operations')['steps']), ready(load_plan('refund_waiting')['steps']))
    session = Conversation(DynamicPlanner(registry, model))
    first = session.submit('分析本周数据并制定大促方案')
    second = session.submit('为订单申请整单退款')
    assert first.status == 'completed' and second.status == 'waiting_approval'
    assert second.report.steps['s2'].result.continuation_token


def test_cli_flags_can_replace_all_four_modules(monkeypatch, capsys):
    monkeypatch.setenv('M3_MODE', 'local')
    monkeypatch.setenv('M4_MODE', 'mock')
    assert cli.main(['--list-capabilities', '--real-m3', '--real-m4', '--real-m5', '--real-m7']) == 0
    catalog = {m['capability_id']: m for m in json.loads(capsys.readouterr().out)}
    assert len(catalog) == 7 and catalog['m7.refund_approval']['supports_resume'] is True
    assert catalog['m3.weekly_report']['version'] == '3.0'
    assert cli.main(['tests/fixtures/operations.json', '--real-m3', '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'completed' and len(report['steps']['s2']['result']['data']['steps']) == 4


@pytest.mark.parametrize('module,args,status', [
    ('agents.plan_execute', ['--week', '2026-W41', '--mode', 'local'], 'completed'),
    ('agents.workflow.refund_graph', [], 'completed'),
    ('agents.workflow.refund_graph', ['--order-id', '2025101234', '--refund-amount', '699.00'], 'waiting_approval')])
def test_standalone_entrypoints_are_json(module, args, status):
    run = subprocess.run([sys.executable, '-m', module, *args], capture_output=True, text=True, encoding='utf-8',
                         env={**__import__('os').environ, 'PYTHONIOENCODING': 'utf-8'})
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)['status'] == status
