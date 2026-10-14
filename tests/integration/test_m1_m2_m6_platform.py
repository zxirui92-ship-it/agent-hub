import json
import os
import subprocess
import sys
import pytest

from agents.single_agent import SingleAgent
from agents.react_agent import ReActAgent
from agents.blackboard import DataFusionModule
from agents.plan_execute import WeeklyReportAgent
from agents.multi_agent import PromotionAgent
from agents.workflow.refund_graph import RefundWorkflow
from agents.router.config import Settings
from agents.router.factory import create_agent
from common.errors import ErrorCode
from hub_platform import cli
from hub_platform.executor import Executor
from hub_platform.conversation import Conversation
from hub_platform.planner import DynamicPlanner
from hub_platform.schema import validate_data
from tests.mocks.agents import FAQMock, OrderTrackingMock, DataFusionMock
from tests.contract.test_contracts import request_for, SAMPLES
from tests.integration.test_m3_m7_platform import replacement_registry
from tests.unit.test_m5_multi_agent import FakeLLM
from tests.unit.test_planner import ScriptedModel, ready
from tests.unit.test_m3_plan_execute import Model


def all_real_registry():
    # Actual architecture implementations, with deliberately offline adapters.
    return replacement_registry(SingleAgent(mode='mock'), ReActAgent(mode='local'),
        DataFusionModule(), WeeklyReportAgent(mode='local'), PromotionAgent(FakeLLM()),
        create_agent(Settings(mode='mock')), RefundWorkflow())


@pytest.mark.parametrize('module,mock,payload', [
    (SingleAgent(mode='mock'), FAQMock, SAMPLES[0]),
    (ReActAgent(mode='local'), OrderTrackingMock, SAMPLES[1]),
    (DataFusionModule(), DataFusionMock, SAMPLES[5])])
def test_shared_manifests_outputs_and_correlations(module, mock, payload, caplog):
    assert module.manifest == mock.manifest
    req = request_for(module.manifest.capability_id, payload)
    req.context['trace_id'] = 'do-not-use-context-trace'
    caplog.set_level('INFO')
    result = module.invoke(req)
    assert result.status == 'completed'
    validate_data(result.data, module.manifest.output_schema, ErrorCode.CONTRACT_MISMATCH)
    assert result.request_id == req.request_id and result.task_id == req.task_id and result.trace_id == req.trace_id
    event = json.loads(caplog.records[-1].message)
    assert event['request_id'] == req.request_id and event['trace_id'] == req.trace_id


def test_all_seven_architectures_invoke_through_executor():
    registry = all_real_registry()
    assert len(registry.list_capabilities()) == 7
    for manifest, payload in zip(registry.list_capabilities(), SAMPLES):
        if manifest.capability_id == 'm4.capability_gateway':
            payload = {'query': 'kb_qa: 优惠政策'}
        plan = {'plan_id': 'plan-20261014-001', 'goal': 'offline architecture integration', 'steps': [
            {'step_id': 's1', 'capability_id': manifest.capability_id,
             'inputs': {k: {'literal': v} for k, v in payload.items()}}]}
        report = Executor(registry).execute(plan)
        assert report.status in ('completed', 'waiting_approval'), report.model_dump_json()


def test_real_fusion_report_promotion_chain_in_topological_order(load_plan):
    registry = all_real_registry()
    report = Executor(registry).execute(load_plan('operations'))
    assert report.status == 'completed'
    assert report.steps['s1'].result.data['fused_data']['revenue_amount'] == 1268430000
    assert report.steps['s2'].inputs['fused_data'] == report.steps['s1'].result.data['fused_data']
    assert '1268430000' in report.steps['s2'].result.data['report_markdown']
    assert report.steps['s3'].inputs['report_markdown'] == report.steps['s2'].result.data['report_markdown']
    assert [e.step_id for e in report.events if e.status == 'running'] == ['s1', 's2', 's3']


@pytest.mark.parametrize('order_id,amount,status', [('order-below', 49999, 'completed'),
    ('order-boundary', 50000, 'completed'), ('order-above', 50001, 'waiting_approval'),
    ('2025101234', 69900, 'waiting_approval')])
def test_real_m2_real_m7_share_order_amount_and_waiting(order_id, amount, status, load_plan):
    plan = load_plan('refund_waiting')
    next(s for s in plan['steps'] if s['step_id'] == 's1')['inputs']['order_id']['literal'] = order_id
    plan['steps'] += [
        {'step_id': 's3', 'capability_id': 'm1.faq_chat', 'depends_on': ['s2'], 'inputs': {'question': {'literal': '退货条件'}}},
        {'step_id': 's4', 'capability_id': 'm1.faq_chat', 'inputs': {'question': {'literal': '退货条件'}}}]
    report = Executor(all_real_registry()).execute(plan)
    assert report.status == status
    assert report.steps['s2'].inputs['refund_amount'] == amount
    assert report.steps['s3'].status == ('pending' if status == 'waiting_approval' else 'completed')
    assert report.steps['s4'].status == 'completed'


def test_order_not_found_blocks_refund_but_not_unrelated_faq(load_plan):
    plan = load_plan('refund_waiting')
    next(s for s in plan['steps'] if s['step_id'] == 's1')['inputs']['order_id']['literal'] = 'absent'
    plan['steps'].append({'step_id': 's3', 'capability_id': 'm1.faq_chat', 'inputs': {'question': {'literal': '售后'}}})
    report = Executor(all_real_registry()).execute(plan)
    assert report.status == 'failed' and report.steps['s1'].error.code == ErrorCode.NOT_FOUND
    assert report.steps['s2'].status == 'skipped' and report.steps['s3'].status == 'completed'


def test_missing_fusion_week_blocks_consumers(load_plan):
    plan = load_plan('operations')
    next(s for s in plan['steps'] if s['step_id'] == 's1')['inputs']['week']['literal'] = '2026-W42'
    report = Executor(all_real_registry()).execute(plan)
    assert report.steps['s1'].error.code == ErrorCode.NOT_FOUND
    assert report.steps['s2'].status == report.steps['s3'].status == 'skipped'


def test_planner_registry_and_m1_session_work_without_planner_changes():
    model = Model('七天', '符合商品完好条件')
    registry = replacement_registry(SingleAgent(model), ReActAgent(mode='local'), DataFusionModule())
    steps = [{'step_id': 's1', 'capability_id': 'm1.faq_chat', 'inputs': {'question': {'literal': '售后政策'}}}]
    planner = ScriptedModel(ready(steps), ready(steps))
    session = Conversation(DynamicPlanner(registry, planner))
    first, second = session.submit('售后政策'), session.submit('有什么条件')
    assert first.status == second.status == 'completed'
    assert first.report.steps['s1'].result.data['session_id'] == second.report.steps['s1'].result.data['session_id']
    assert len(json.loads(model.calls[1][1])['history']) == 2


def test_cli_all_seven_flags_and_local_chains(monkeypatch, capsys):
    for name, value in [('M1_MODE', 'mock'), ('M2_MODE', 'local'), ('M3_MODE', 'local'), ('M4_MODE', 'mock')]:
        monkeypatch.setenv(name, value)
    flags = [f'--real-m{i}' for i in range(1, 8)]
    assert cli.main(['--list-capabilities', *flags]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 7
    assert cli.main(['tests/fixtures/refund_waiting.json', '--real-m2', '--real-m7', '--json']) == 3
    assert json.loads(capsys.readouterr().out)['status'] == 'waiting_approval'
    assert cli.main(['tests/fixtures/operations.json', '--real-m6', '--real-m3', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['steps']['s1']['result']['data']['fused_data']['revenue_amount'] == 1268430000


@pytest.mark.parametrize('module,args,code', [
    ('agents.single_agent', ['退货政策', '--mode', 'mock'], 0),
    ('agents.react_agent', ['--mode', 'local'], 0),
    ('agents.react_agent', ['--mode', 'local', '--order-id', 'absent'], 1),
    ('agents.blackboard', ['--week', '2026-W41'], 0),
    ('agents.blackboard', ['--week', '2026-W42'], 1)])
def test_independent_cli(module, args, code):
    run = subprocess.run([sys.executable, '-m', module, *args], capture_output=True, text=True,
                         encoding='utf-8', env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    assert run.returncode == code, run.stderr
    assert json.loads(run.stdout)['status'] == ('completed' if code == 0 else 'failed')
