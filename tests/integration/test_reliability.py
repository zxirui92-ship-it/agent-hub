"""Combined audit + imported-data regressions, with no paid services."""
import json
from pathlib import Path

import pytest

from agents.react_agent import ReActAgent
from agents.workflow.refund_graph import RefundWorkflow
from common.business_data import BusinessData
from common.errors import ErrorCode, ServiceError
from common.knowledge import KnowledgeBase
from hub_platform.errors import HubError
from hub_platform.executor import Executor
from hub_platform.schema import validate_data
from tests.contract.test_contracts import request_for
from tests.integration.test_prd_completion import approval_plan, decision, replacement_registry

DATA = Path(__file__).resolve().parents[2] / 'data/group02'
ORDERS = json.loads((DATA/'order_basic.json').read_text(encoding='utf-8'))
ENTRIES = BusinessData(DATA).knowledge_entries()


@pytest.mark.parametrize('entry', ENTRIES, ids=lambda entry:entry['entry_id'])
def test_every_knowledge_entry_is_retrievable_with_its_source(entry):
    result = KnowledgeBase(data=BusinessData(DATA)).search(entry['title'])
    assert entry['entry_id'] in {source['entry_id'] for source in result['sources']}
    assert entry['content'] in result['answer']


@pytest.mark.parametrize('row', ORDERS, ids=lambda row:row['order_id'])
def test_every_imported_order_returns_truthful_order_and_logistics_summary(monkeypatch, row):
    monkeypatch.setenv('HUB_DATA_DIR', str(DATA))
    agent = ReActAgent(mode='local')
    result = agent.invoke(request_for(agent.manifest.capability_id, {'order_id':row['order_id']}))
    assert result.status == 'completed', result.model_dump_json()
    validate_data(result.data, agent.manifest.output_schema, ErrorCode.CONTRACT_MISMATCH)
    assert result.data['order_amount'] == row['order_amount']
    assert len(result.data['observations']) == 2
    if result.data['logistics_availability'] == 'available':
        assert result.data['tracking_number'] and not result.data['warnings']
    else:
        assert result.data['tracking_number'] == '' and result.data['warnings']


@pytest.mark.parametrize('row', ORDERS, ids=lambda row:row['order_id'])
def test_every_imported_refund_has_a_business_outcome_or_explicit_source_conflict(monkeypatch, row):
    monkeypatch.setenv('HUB_DATA_DIR', str(DATA))
    source = BusinessData(DATA)
    agent = RefundWorkflow()
    result = agent.invoke(request_for(agent.manifest.capability_id, {
        'order_id':row['order_id'], 'refund_amount':row['order_amount'], 'reason':'模拟退货'}))
    try:
        fact = source.refund_order(row['order_id'])
    except ServiceError as exc:
        assert result.status == 'failed' and result.error.code == exc.code
        assert '客户不一致' in result.error.message
        return
    assert result.status in ('completed','waiting_approval'), result.model_dump_json()
    if fact['order_status'] in ('pending_payment','refunding','refunded','canceled'):
        assert result.data['approval_status'] == 'rejected'
    elif fact['order_amount'] > 50000 or fact['risk_level'] == 'high_risk':
        assert result.status == 'waiting_approval'
        final = agent.submit_decision(result.continuation_token, approved=True,
                                      reviewer='模拟审核员', material_complete=True)
        assert final.status == 'completed' and final.data['approval_status'] == 'approved'
    else:
        assert result.data['approval_status'] == 'approved'


def test_platform_recovers_committed_approval_without_reexecuting_graph(load_plan, monkeypatch):
    module = RefundWorkflow()
    executor = Executor(replacement_registry(module))
    first = executor.execute(approval_plan(load_plan))
    original = module._result
    monkeypatch.setattr(module, '_result', lambda *a: (_ for _ in ()).throw(RuntimeError('response failure')))
    with pytest.raises(HubError) as exc:
        executor.resume(first.task_id, 's2', decision())
    assert exc.value.retryable and exc.value.code == ErrorCode.INTERNAL_ERROR
    committed_trace = module.get_request_trace(first.steps['s2'].request_id)
    # A changed decision cannot replace the already committed one.
    with pytest.raises(HubError) as exc:
        executor.resume(first.task_id, 's2', decision(approved=False))
    assert exc.value.code == ErrorCode.INVALID_INPUT
    monkeypatch.setattr(module, '_result', original)
    final = executor.resume(first.task_id, 's2', decision())
    assert final.status == 'completed' and final.steps['s3'].status == 'completed'
    assert module.get_request_trace(first.steps['s2'].request_id) == committed_trace
    assert sum(n['node_name']=='manual_review' for n in final.steps['s2'].result.data['node_trace']) == 1


def test_unknown_order_remains_not_found(monkeypatch):
    monkeypatch.setenv('HUB_DATA_DIR', str(DATA))
    agent = ReActAgent(mode='local')
    result = agent.invoke(request_for(agent.manifest.capability_id, {'order_id':'missing-order'}))
    assert result.status == 'failed' and result.error.code == ErrorCode.NOT_FOUND


def test_refund_trace_preserves_cent_precision_and_large_amounts():
    from agents.workflow.formatting import format_amount
    assert format_amount(50001, digits=0) == '500.01 元'
    assert format_amount(50000, digits=0) == '500 元'
    assert format_amount(9007199254740993) == '90071992547409.93 元'
