"""Real imported files + real module code; models remain explicitly offline."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from agents.blackboard import DataFusionModule
from agents.plan_execute import load_sample_view
from agents.react_agent import ReActAgent
from agents.router.skills.kb_qa import KbQaSkill
from agents.single_agent import SingleAgent
from agents.workflow.refund_graph import RefundWorkflow
from common.business_data import BusinessData, configured_data
from common.errors import ErrorCode, ServiceError
from common.knowledge import KnowledgeBase
from hub_platform.executor import Executor
from tests.contract.test_contracts import request_for
from tests.integration.test_m1_m2_m6_platform import all_real_registry

DATA = Path(__file__).resolve().parents[2] / 'data/group02'


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setenv('HUB_DATA_DIR', str(DATA))
    monkeypatch.delenv('M6_DATA_DIR', raising=False)
    return BusinessData(DATA)


def invoke(module, **payload):
    return module.invoke(request_for(module.manifest.capability_id, payload))


def test_provenance_and_original_files():
    manifest = json.loads((DATA / 'source_manifest.json').read_text(encoding='utf-8'))
    assert manifest['branch'] == 'group_02'
    assert manifest['commit'] == '7f70950d6cfea4cab0f8a8b996e176d5eee55ae2'
    assert len(manifest['files']) == 14
    for file in manifest['files']:
        assert sha256((DATA / file['file']).read_bytes()).hexdigest() == file['sha256']


def test_config_is_relative_to_project_not_cwd(source, monkeypatch, tmp_path):
    monkeypatch.setenv('HUB_DATA_DIR', 'data/group02')
    monkeypatch.chdir(tmp_path)
    assert configured_data().order('2025101234')['order_amount'] == 2397.0
    with pytest.raises(ServiceError) as exc:
        configured_data().order('order-low')
    assert exc.value.code == ErrorCode.NOT_FOUND  # no silent old-fixture fallback


def test_knowledge_shared_by_m1_and_m4_with_sources(source):
    query = '保修'
    evidence = json.loads(KbQaSkill().run({'query': query}))
    assert evidence['source_kind'] == 'imported_simulation'
    assert {e['entry_id'] for e in evidence['sources']} == {'F019', 'SP007'}
    assert '2 年' in evidence['answer'] and '1 年保修' in evidence['answer']
    assert '待确认' in evidence['warnings'][0]
    calls = []
    class Model:
        def complete(self, system, prompt):
            calls.append((system, json.loads(prompt)))
            return 'F019 与 SP007 保修期限不一致，请业务负责人确认。'
    result = invoke(SingleAgent(Model()), question=query)
    assert result.status == 'completed'
    tools = calls[0][1]['tool_results']
    assert set(tools) == {'lookup_faq', 'get_service_policy'}
    assert all(json.loads(value)['sources'] == evidence['sources'] or
               {s['entry_id'] for s in json.loads(value)['sources']} == {'F019', 'SP007'} for value in tools.values())
    assert '冲突' in calls[0][0]
    assert len(source.knowledge_entries()) == 34
    with pytest.raises(ServiceError) as exc:
        KnowledgeBase().search('量子引力场方程')
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_custom_m4_knowledge_overrides_dataset(source, tmp_path):
    path = tmp_path / 'kb.json'
    path.write_text(json.dumps([{'entry_id': 'x', 'title': '请假', 'content': '提前两天申请', 'keywords': ['请假']}]), encoding='utf-8')
    value = json.loads(KbQaSkill(path).run({'query': '请假'}))
    assert value['source_kind'] == 'configured_knowledge' and value['answer'] == '提前两天申请'


def test_order_money_status_and_logistics(source):
    result = invoke(ReActAgent(mode='local'), order_id='2025100003')
    assert result.status == 'completed'
    assert result.data['order_amount'] == 129.0 and result.data['order_status'] == 'delivered'
    observations = [json.loads(o) for o in result.data['observations']]
    assert all(o['result']['source'] == 'imported_simulation' for o in observations)
    assert observations[1]['result']['tracking_history'] == source.logistics('2025100003')['tracking_history']
    assert not any(k in observations[0]['result'] for k in ('customer_name', 'phone', 'shipping_address'))


def test_source_conflicts_are_reported_without_repairing_facts(source):
    bad = invoke(ReActAgent(mode='local'), order_id='2025101234')
    assert bad.status == 'completed' and bad.data['order_amount'] == 2397.0
    assert bad.data['logistics_availability'] == 'inconsistent' and bad.data['tracking_number'] == ''
    assert '早于' in bad.data['warnings'][0]
    bad_refund = invoke(RefundWorkflow(), order_id='2025101234', refund_amount=2397.0, reason='退款')
    assert bad_refund.error.code == ErrorCode.CONTRACT_MISMATCH and '客户不一致' in bad_refund.error.message
    missing = next(oid for oid in source.rows('order_basic', 'order_id') if oid not in source.rows('logistics_status', 'order_id'))
    result = invoke(ReActAgent(mode='local'), order_id=missing)
    assert result.status == 'completed' and result.data['logistics_availability'] == 'unavailable'
    assert result.data['tracking_number'] == '' and result.data['warnings']


@pytest.mark.parametrize('week', ['2025-W40', '2025-W41', '2025-W42', '2025-W43'])
def test_weekly_fusion_uses_uv_ratio_and_integer_cents(source, week):
    result = invoke(DataFusionModule(), week=week)
    assert result.status == 'completed'
    view = result.data['fused_data']
    behavior = source.read('user_behavior_weekly')[week]
    assert view['revenue_amount'] == source.read('weekly_sales')[week]['gmv_amount']
    assert type(view['revenue_amount']) is float
    assert view['conversion_rate'] == behavior['order_uv']/behavior['uv']
    assert '不是利润 ROI' in view['anomaly'] and '漏斗' in view['anomaly']
    assert load_sample_view(week) == view
    assert any('非生产' in field for field in result.data['field_definitions'])


def test_real_seven_module_chain_uses_imported_week(source, load_plan):
    plan = load_plan('operations')
    next(s for s in plan['steps'] if s['step_id'] == 's1')['inputs']['week']['literal'] = '2025-W41'
    plan['steps'].extend([
        {'step_id': 's4', 'capability_id': 'm1.faq_chat', 'inputs': {'question': {'literal': '退货条件'}}},
        {'step_id': 's5', 'capability_id': 'm4.capability_gateway', 'inputs': {'query': {'literal': 'kb_qa: 退货条件'}}}])
    registry = all_real_registry()
    assert len(registry.list_capabilities()) == 7
    report = Executor(registry).execute(plan)
    assert report.status == 'completed', report.model_dump_json()
    assert report.steps['s1'].result.data['fused_data']['revenue_amount'] == 12680000.0
    assert '12680000.00' in report.steps['s2'].result.data['report_markdown']
    assert report.steps['s3'].inputs['fused_data'] == report.steps['s1'].result.data['fused_data']
    assert json.loads(report.steps['s5'].result.data['result'])['source_kind'] == 'imported_simulation'
    assert [e.step_id for e in report.events if e.status == 'running' and e.step_id in ('s1', 's2', 's3')] == ['s1', 's2', 's3']


@pytest.mark.parametrize('order_id,amount,status', [('2025100003',129.0,'completed'), ('2025100004',1099.0,'waiting_approval')])
def test_real_order_refund_chain_and_waiting(source, load_plan, order_id, amount, status):
    plan = load_plan('refund_waiting')
    plan['steps'][0]['inputs']['order_id']['literal'] = order_id
    plan['steps'].append({'step_id':'s3', 'capability_id':'m1.faq_chat', 'depends_on':['s2'], 'inputs':{'question':{'literal':'退货'}}})
    report = Executor(all_real_registry()).execute(plan)
    assert report.status == status, report.model_dump_json()
    assert report.steps['s2'].inputs['refund_amount'] == amount
    assert report.steps['s3'].status == ('completed' if status == 'completed' else 'pending')
    assert invoke(RefundWorkflow(), order_id=order_id, refund_amount=0.01, reason='退款').error.code == ErrorCode.INVALID_INPUT


def test_bad_order_blocks_downstream_while_faq_continues(source, load_plan):
    plan = load_plan('refund_waiting')
    plan['steps'].append({'step_id':'s3', 'capability_id':'m1.faq_chat', 'inputs':{'question':{'literal':'发票'}}})
    report = Executor(all_real_registry()).execute(plan)
    assert report.status == 'failed'
    assert report.steps['s1'].status == 'completed'
    assert report.steps['s1'].result.data['logistics_availability'] == 'inconsistent'
    assert report.steps['s2'].error.code == ErrorCode.CONTRACT_MISMATCH
    assert report.steps['s3'].status == 'completed'


@pytest.fixture
def editable(source, tmp_path):
    shutil.copytree(DATA, tmp_path / 'data')
    return BusinessData(tmp_path / 'data')


def change(source, name, transform):
    data = json.loads((source.path / f'{name}.json').read_text(encoding='utf-8'))
    transform(data)
    (source.path / f'{name}.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


@pytest.mark.parametrize('value', [129.0, True, -1, '12900'])
def test_reject_non_cent_money(editable, value):
    change(editable, 'order_basic', lambda rows: rows[0].update(order_amount=value))
    with pytest.raises(ServiceError) as exc:
        editable.order('2025101234')
    assert exc.value.code == ErrorCode.CONTRACT_MISMATCH


def test_funnel_uses_people_not_order_count_and_returns_deep_copy(editable):
    change(editable, 'weekly_sales', lambda rows: rows['2025-W41'].update(order_count=999))
    loaded = editable.load('2025-W41')
    assert loaded['behavior']['conversion_rate'] == 66200 / 472000
    loaded['orders']['gmv_amount'] = 0.0
    assert editable.load('2025-W41')['orders']['gmv_amount'] == 12680000.0


def test_duplicate_keys_and_invalid_week_fail_explicitly(editable):
    change(editable, 'order_basic', lambda rows: rows.append(deepcopy(rows[0])))
    with pytest.raises(ServiceError) as exc:
        editable.order('2025101234')
    assert exc.value.code == ErrorCode.CONTRACT_MISMATCH
    for week in ('2025-41', '2025-W99', '2025-W00'):
        with pytest.raises(ServiceError) as exc:
            editable.load(week)
        assert exc.value.code == ErrorCode.INVALID_INPUT


def test_imported_refund_policy_routes_high_risk_small_amount_to_manual(editable, monkeypatch):
    customer = editable.order('2025100003')['customer_id']
    change(editable, 'refund_compliance_policy', lambda p: p['risk_users'].update({customer:{'risk_level':'high_risk','note':'测试风险'}}))
    monkeypatch.setenv('HUB_DATA_DIR', str(editable.path))
    module = RefundWorkflow()
    result = invoke(module, order_id='2025100003', refund_amount=129.0, reason='退货')
    assert result.status == 'waiting_approval' and '高风险' in result.waiting_reason
    assert 'auto_approve' not in [n['node_name'] for n in result.data['node_trace']]
    state = module.get_request_trace(result.request_id)[0]['state']
    assert state['max_reflection'] == 2 and state['auto_approve_amount'] == 500.0
    completed = module.submit_decision(result.continuation_token, approved=True, reviewer='测试审核员', material_complete=True)
    assert completed.status == 'completed' and completed.data['approval_status'] == 'approved'


@pytest.mark.parametrize('status', ['pending_payment', 'refunding', 'refunded', 'canceled'])
def test_nonrefundable_status_cannot_autoapprove(source, status):
    module = RefundWorkflow(order_loader=lambda _: {'order_amount':1.0, 'order_status':status})
    result = invoke(module, order_id='test', refund_amount=1.0, reason='测试')
    assert result.status == 'completed' and result.data['approval_status'] == 'rejected'


@pytest.mark.parametrize('change_field', ['refund_amount', 'requested_at', 'customer_id'])
def test_refund_history_contradictions_cannot_be_approved(editable, change_field):
    fact = editable.order('2025100003')
    record = {'refund_id':'test-refund', 'order_id':'2025100003', 'customer_id':fact['customer_id'],
              'refund_amount':fact['order_amount'], 'requested_at':fact['created_at']}
    record[change_field] = {'refund_amount':0.01, 'requested_at':'2000-01-01T00:00:00+08:00', 'customer_id':'wrong'}[change_field]
    change(editable, 'refund_request', lambda rows: rows.append(record))
    with pytest.raises(ServiceError) as exc:
        editable.refund_order('2025100003')
    assert exc.value.code == ErrorCode.CONTRACT_MISMATCH


def test_refund_threshold_cannot_silently_change(editable):
    change(editable, 'refund_compliance_policy', lambda policy: policy.update(auto_approve_amount=5.0))
    with pytest.raises(ServiceError) as exc:
        editable.refund_policy()
    assert exc.value.code == ErrorCode.CONTRACT_MISMATCH
