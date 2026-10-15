"""Deterministic regressions for risk routing and committed-decision recovery."""
from copy import deepcopy

import pytest

from agents.workflow.nodes import auto_approve_node, compliance_check_node, route_by_amount
from agents.workflow.refund_graph import RefundWorkflow
from common.errors import ErrorCode, ServiceError
from tests.unit.test_m7_workflow import request


def workflow(amount=699.0, **fields):
    fact = {'order_amount': amount, 'order_status': 'paid', **fields}
    return RefundWorkflow(order_loader=lambda _: deepcopy(fact))


def decide(agent, token, *, approved=True, material_complete=True):
    return agent.submit_decision(token, approved=approved, reviewer='审核人',
                                 material_complete=material_complete)


@pytest.mark.parametrize('amount', [0.01, 199.0, 500.0])
def test_small_high_risk_refund_requires_explicit_review_and_materials(amount):
    agent = workflow(amount, risk_level='high_risk')
    first = agent.invoke(request(amount=amount))
    assert first.status == 'waiting_approval' and '高风险' in first.waiting_reason
    assert first.data['node_trace'] == [{'node_name': 'receive'}]
    state = agent.get_request_trace(first.request_id)[0]['state']
    assert state['requires_manual'] is True and state['material_complete'] is False

    incomplete = decide(agent, first.continuation_token, material_complete=False)
    assert incomplete.status == 'waiting_approval' and 'R3' in incomplete.waiting_reason
    state = agent.get_request_trace(first.request_id)[0]['state']
    assert state['failed_rules'] == ['R3']
    assert state['material_complete'] is False and state['human_decision'] == ''

    final = decide(agent, incomplete.continuation_token)
    assert final.status == 'completed' and final.data['approval_status'] == 'approved'
    state = agent.get_request_trace(first.request_id)[0]['state']
    assert state['decision'] == 'manual_approved' and state['material_complete'] is True
    assert state['failed_rules'] == []
    assert 'auto_approve' not in [node['node_name'] for node in final.data['node_trace']]


@pytest.mark.parametrize('amount', [199.0, 500.0, 500.01])
def test_high_risk_refund_can_be_rejected_without_documents(amount):
    agent = workflow(amount, risk_level='high_risk')
    waiting = agent.invoke(request(amount=amount))
    final = decide(agent, waiting.continuation_token, approved=False, material_complete=False)
    assert final.data['approval_status'] == 'rejected'
    assert final.data['node_trace'] == [
        {'node_name': 'receive'}, {'node_name': 'manual_review'}, {'node_name': 'finalize'}]


@pytest.mark.parametrize('material_complete', [False, True])
def test_auto_approval_does_not_rewrite_material_evidence(material_complete):
    update = auto_approve_node({'refund_amount': 199.0, 'material_complete': material_complete})
    assert 'material_complete' not in update
    agent = workflow(199.0)
    result = agent.invoke(request(amount=199.0))
    assert result.data['approval_status'] == 'approved'
    assert agent.get_request_trace(result.request_id)[0]['state']['material_complete'] is False


@pytest.mark.parametrize('status', ['paid', 'shipped', 'delivered'])
@pytest.mark.parametrize('amount', [199.0, 500.0, 500.01])
def test_known_refundable_statuses_keep_valid_workflows(status, amount):
    agent = workflow(amount, order_status=status)
    result = agent.invoke(request(amount=amount))
    if amount > 500.0:
        assert result.status == 'waiting_approval'
        result = decide(agent, result.continuation_token)
    assert result.status == 'completed' and result.data['approval_status'] == 'approved'


@pytest.mark.parametrize('status', [None, '', 'unknown', 'CANCELED', 123, [], {}, True])
def test_untrusted_provider_status_fails_before_any_checkpoint(status):
    agent = workflow(199.0, order_status=status)
    result = agent.invoke(request(amount=199.0))
    assert result.status == 'failed' and result.error.code == ErrorCode.CONTRACT_MISMATCH
    assert result.error.retryable is False
    assert not agent._requests and not agent._pending
    # The graph's routing and compliance checks also fail closed in isolation.
    state = {'order_status': status, 'refund_amount': 199.0, 'order_amount': 199.0}
    assert route_by_amount(state) == 'reject'
    assert 'R2' in compliance_check_node(state)['failed_rules']


@pytest.mark.parametrize('fact', [None, [], {}, {'order_amount': 199.0},
    {'order_amount': 199.001, 'order_status': 'paid'},
    {'order_amount': True, 'order_status': 'paid'},
    {'order_amount': 0.0, 'order_status': 'paid'}])
def test_invalid_order_fact_is_a_source_contract_error(fact):
    agent = RefundWorkflow(order_loader=lambda _: fact)
    result = agent.invoke(request(amount=199.0))
    assert result.status == 'failed' and result.error.code == ErrorCode.CONTRACT_MISMATCH
    assert not agent._requests and not agent._pending


@pytest.mark.parametrize('risk_level', [None, '', 'unknown', 'HIGH_RISK', 123, [], {}, True])
def test_invalid_supplied_risk_never_defaults_to_normal(risk_level):
    agent = workflow(199.0, risk_level=risk_level)
    result = agent.invoke(request(amount=199.0))
    assert result.status == 'failed' and result.error.code == ErrorCode.CONTRACT_MISMATCH
    assert not agent._requests and not agent._pending


@pytest.mark.parametrize('fields', [{}, {'risk_level': 'normal'}])
def test_missing_or_explicit_normal_risk_keeps_small_refund_behavior(fields):
    agent = workflow(199.0, **fields)
    result = agent.invoke(request(amount=199.0))
    assert result.status == 'completed' and result.data['approval_status'] == 'approved'


@pytest.mark.parametrize('approved,complete,expected', [
    (True, True, 'approved'), (False, False, 'rejected'), (True, False, 'waiting_approval')])
@pytest.mark.parametrize('after_build', [False, True])
def test_result_recovery_never_replays_a_committed_review(monkeypatch, approved, complete, expected, after_build):
    agent = workflow()
    waiting = agent.invoke(request())
    token = waiting.continuation_token
    original_result = agent._result

    def broken_result(*args, **kwargs):
        if after_build:
            original_result(*args, **kwargs)
        raise RuntimeError('response failed after commit')

    monkeypatch.setattr(agent, '_result', broken_result)
    failed = decide(agent, token, approved=approved, material_complete=complete)
    assert failed.status == 'failed' and failed.error.code == ErrorCode.INTERNAL_ERROR
    assert failed.error.retryable is True
    committed_trace = agent.get_request_trace(waiting.request_id)
    assert set(agent._pending) == {token}, 'A failed response must not publish an orphan continuation'
    assert set(agent._submitted) == {token}

    # Multiple failed response retries must neither run a new review nor reflect again.
    assert decide(agent, token, approved=approved, material_complete=complete).status == 'failed'
    assert agent.get_request_trace(waiting.request_id) == committed_trace
    assert set(agent._pending) == {token}

    monkeypatch.setattr(agent, '_result', original_result)
    result = decide(agent, token, approved=approved, material_complete=complete)
    assert result.data['approval_status'] == expected
    assert agent.get_request_trace(waiting.request_id) == committed_trace
    assert [node['node_name'] for node in result.data['node_trace']].count('manual_review') == 1
    for key in ('task_id', 'trace_id', 'request_id', 'capability_id'):
        assert getattr(result, key) == getattr(waiting, key)
    assert not agent._submitted
    with pytest.raises(ServiceError) as consumed:
        decide(agent, token)
    assert consumed.value.code == ErrorCode.NOT_FOUND

    if expected == 'waiting_approval':
        assert result.continuation_token != token
        assert set(agent._pending) == {result.continuation_token}
        final = decide(agent, result.continuation_token)
        assert final.data['approval_status'] == 'approved'
        assert [node['node_name'] for node in final.data['node_trace']].count('manual_review') == 2
    else:
        assert not agent._pending


def test_committed_decision_cannot_be_replaced_during_result_recovery(monkeypatch):
    agent = workflow()
    waiting = agent.invoke(request())
    original_result = agent._result
    monkeypatch.setattr(agent, '_result', lambda *args: (_ for _ in ()).throw(RuntimeError('response failed')))
    assert decide(agent, waiting.continuation_token, approved=False).status == 'failed'
    committed_trace = agent.get_request_trace(waiting.request_id)
    monkeypatch.setattr(agent, '_result', original_result)

    replacement = decide(agent, waiting.continuation_token, approved=True)
    assert replacement.status == 'failed' and replacement.error.code == ErrorCode.INVALID_INPUT
    assert agent.get_request_trace(waiting.request_id) == committed_trace
    recovered = decide(agent, waiting.continuation_token, approved=False)
    assert recovered.data['approval_status'] == 'rejected'


@pytest.mark.parametrize('approved,complete,expected', [
    (True, True, 'approved'), (False, False, 'rejected'), (True, False, 'waiting_approval')])
@pytest.mark.parametrize('failed_read', [1, 2])
def test_resume_snapshot_failure_before_or_after_commit_keeps_token_recoverable(
        monkeypatch, approved, complete, expected, failed_read):
    agent = workflow()
    waiting = agent.invoke(request())
    token = waiting.continuation_token
    original_get_state = agent.graph.get_state
    reads = 0

    def get_state(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads == failed_read:
            raise RuntimeError('one-shot checkpoint response read failure')
        return original_get_state(*args, **kwargs)

    monkeypatch.setattr(agent.graph, 'get_state', get_state)
    failed = decide(agent, token, approved=approved, material_complete=complete)
    assert failed.status == 'failed' and failed.error.code == ErrorCode.INTERNAL_ERROR
    assert failed.error.retryable is (failed_read == 2)
    trace_after_failure = agent.get_request_trace(waiting.request_id)
    nodes = [node['node_name'] for node in trace_after_failure[0]['state']['node_trace']]
    assert nodes.count('manual_review') == (1 if failed_read == 2 else 0)
    assert (token in agent._submitted) is (failed_read == 2)
    assert set(agent._pending) == {token}

    monkeypatch.setattr(agent.graph, 'get_state', original_get_state)
    recovered = decide(agent, token, approved=approved, material_complete=complete)
    assert recovered.data['approval_status'] == expected
    assert [node['node_name'] for node in recovered.data['node_trace']].count('manual_review') == 1
    if failed_read == 2:
        assert agent.get_request_trace(waiting.request_id) == trace_after_failure
    assert not agent._submitted
    with pytest.raises(ServiceError) as consumed:
        decide(agent, token, approved=approved, material_complete=complete)
    assert consumed.value.code == ErrorCode.NOT_FOUND

    if expected == 'waiting_approval':
        assert set(agent._pending) == {recovered.continuation_token}
        assert decide(agent, recovered.continuation_token).data['approval_status'] == 'approved'
    else:
        assert not agent._pending
