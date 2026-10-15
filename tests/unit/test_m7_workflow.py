import pytest

from agents.workflow.refund_graph import RefundWorkflow
from common.errors import ErrorCode, ServiceError
from tests.contract.test_contracts import request_for


def request(order='2025101234', amount=699.0, **updates):
    value = request_for('m7.refund_approval', {'order_id': order, 'refund_amount': amount, 'reason': '退货'})
    return value.model_copy(update=updates)


@pytest.mark.parametrize('order,amount,status', [('order-low', 199.0, 'completed'),
    ('order-below', 499.99, 'completed'), ('order-boundary', 500.0, 'completed'),
    ('order-above', 500.01, 'waiting_approval')])
def test_real_graph_amount_boundaries(order, amount, status):
    agent = RefundWorkflow()
    value = agent.invoke(request(order, amount))
    assert value.status == status
    nodes = [x['node_name'] for x in value.data['node_trace']]
    if status == 'completed':
        assert nodes == ['receive', 'auto_approve', 'compliance_check', 'finalize']
        assert value.data['approval_status'] == 'approved'
    else:
        assert nodes == ['receive'] and value.continuation_token
    assert value.data['state_view']['refund_amount'] == amount


@pytest.mark.parametrize('amount', [0.01, 699.01, 699.001, True, '69900', -0.01])
def test_amount_cannot_override_order_fact(amount):
    result = RefundWorkflow().invoke(request(amount=amount))
    assert result.status == 'failed' and result.error.code == ErrorCode.INVALID_INPUT


@pytest.mark.parametrize('order,code', [('missing', ErrorCode.NOT_FOUND), ('unavailable', ErrorCode.TOOL_UNAVAILABLE)])
def test_data_errors_are_structured(order, code):
    result = RefundWorkflow().invoke(request(order))
    assert result.status == 'failed' and result.error.code == code
    assert result.error.request_id == result.request_id


@pytest.mark.parametrize('approved,status', [(True, 'approved'), (False, 'rejected')])
def test_explicit_decision_resumes_and_preserves_correlation(approved, status):
    agent = RefundWorkflow()
    initial = agent.invoke(request())
    result = agent.submit_decision(initial.continuation_token, approved=approved, reviewer='测试审核人', material_complete=True)
    assert result.status == 'completed' and result.data['approval_status'] == status
    assert result.continuation_token is None
    for key in ('task_id', 'trace_id', 'request_id', 'capability_id'):
        assert getattr(result, key) == getattr(initial, key)
    assert result.data['request_id'] == initial.data['request_id']
    nodes = [x['node_name'] for x in result.data['node_trace']]
    assert nodes.count('receive') == 1 and nodes.count('manual_review') == 1
    if not approved:
        assert 'compliance_check' not in nodes
    with pytest.raises(ServiceError) as exc:
        agent.submit_decision(initial.continuation_token, approved=True, reviewer='测试审核人', material_complete=True)
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_missing_material_reflects_then_requires_a_fresh_decision():
    agent = RefundWorkflow()
    first = agent.invoke(request())
    again = agent.submit_decision(first.continuation_token, approved=True, reviewer='初审', material_complete=False)
    assert again.status == 'waiting_approval'
    assert again.continuation_token != first.continuation_token and 'R4' in again.waiting_reason
    state = agent.get_request_trace(first.request_id)[0]['state']
    assert state['human_decision'] == '' and state['reflection_count'] == 1
    final = agent.submit_decision(again.continuation_token, approved=True, reviewer='复审', material_complete=True)
    assert final.status == 'completed' and final.data['approval_status'] == 'approved'
    nodes = [x['node_name'] for x in final.data['node_trace']]
    assert nodes == ['receive', 'manual_review', 'compliance_check', 'reflect', 'manual_review', 'compliance_check', 'finalize']


def test_original_reflection_limit_ends_in_business_rejection():
    agent = RefundWorkflow()
    value = agent.invoke(request())
    for _ in range(3):
        value = agent.submit_decision(value.continuation_token, approved=True, reviewer='审核', material_complete=False)
    assert value.status == 'completed' and value.data['approval_status'] == 'rejected'
    assert value.continuation_token is None


def test_invalid_decision_does_not_consume_token():
    agent = RefundWorkflow()
    value = agent.invoke(request())
    bad = agent.submit_decision(value.continuation_token, approved='yes', reviewer='测试', material_complete=True)
    assert bad.status == 'failed' and bad.error.code == ErrorCode.INVALID_INPUT
    good = agent.submit_decision(value.continuation_token, approved=True, reviewer='测试', material_complete=True)
    assert good.data['approval_status'] == 'approved'


def test_pending_requests_are_isolated():
    agent = RefundWorkflow()
    first = agent.invoke(request())
    second = agent.invoke(request(request_id='req-000000000002', task_id='task-000000000002'))
    a = agent.submit_decision(first.continuation_token, approved=False, reviewer='测试', material_complete=False)
    b = agent.submit_decision(second.continuation_token, approved=True, reviewer='测试', material_complete=True)
    assert a.request_id != b.request_id and a.task_id != b.task_id
    assert a.data['approval_status'] == 'rejected' and b.data['approval_status'] == 'approved'
    with pytest.raises(ServiceError):
        RefundWorkflow().submit_decision(first.continuation_token, approved=True, reviewer='测试', material_complete=True)


@pytest.mark.parametrize('status', ['canceled', 'refunded'])
def test_non_refundable_order_is_rejected_before_manual_gate(status):
    agent = RefundWorkflow(order_loader=lambda _: {'order_amount': 699.0, 'order_status': status})
    result = agent.invoke(request())
    assert result.status == 'completed' and result.data['approval_status'] == 'rejected'
    assert [node['node_name'] for node in result.data['node_trace']] == ['receive', 'finalize']


def test_checkpoint_rollback_preserves_history_without_duplicate_reducers():
    agent = RefundWorkflow()
    state = agent.run('order-low', '退货', refund_amount=199.0, thread_id='rollback-test')
    history = agent.get_trace('rollback-test')
    restored = agent.rollback('rollback-test', steps_back=1)
    assert restored['node_trace'] == history[1]['state']['node_trace']
    assert len(restored['node_trace']) < len(state['node_trace'])
    assert len(restored['rollback_log']) == 1
    resumed = agent.resume('rollback-test')
    assert resumed['approval_status'] == 'approved'
    assert resumed['node_trace'] == state['node_trace']
    assert 'manual_review' in agent.mermaid() and 'reflect' in agent.mermaid()
