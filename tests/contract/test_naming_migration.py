import re
from datetime import datetime

import pytest
from pydantic import ValidationError

from common.contracts import AgentRequest, AgentResult, ErrorDetail
from common.errors import ErrorCode
from hub_platform.errors import HubError
from hub_platform.executor import Executor
from tests.contract.test_contracts import request_for, SAMPLES
from tests.mocks.agents import MOCK_TYPES, RefundApprovalMock, OrderTrackingMock


def test_catalog_fields_owners_and_old_id_removed(registry):
    fields = [set(x.split()) for x in ["answer session_id", "order_id order_status tracking_number actions observations stop_reason order_amount",
        "week report_markdown steps", "skill_name result route_reason", "plan_markdown roles", "fused_data field_definitions update_events",
        "request_id approval_status node_trace state_view"]]
    for cls, expected in zip(MOCK_TYPES, fields):
        spec = registry.get_manifest(cls.manifest.capability_id)
        assert expected <= set(spec.output_schema['required'])
        versions = {'m1.faq_chat': '1.1', 'm2.order_tracking': '2.0', 'm3.weekly_report': '3.0',
                    'm4.capability_gateway': '1.0', 'm5.promotion_plan': '3.0', 'm6.data_fusion': '2.0',
                    'm7.refund_approval': '3.0'}
        assert spec.version == versions[spec.capability_id]
        assert 'pending' not in spec.owner
    with pytest.raises(HubError) as exc:
        registry.get('m1.faq')
    assert exc.value.code == ErrorCode.UNKNOWN_CAPABILITY


@pytest.mark.parametrize('amount', [0.01, 500.0, 698.99, 699.01, 699.001, True, '69900'])
def test_refund_cannot_override_order_fact(amount):
    req = request_for('m7.refund_approval', {'order_id': '2025101234', 'refund_amount': amount, 'reason': '退货'})
    value = RefundApprovalMock().invoke(req)
    assert value.status == 'failed' and value.error.code == ErrorCode.INVALID_INPUT
    assert not value.error.retryable and value.error.request_id == req.request_id


@pytest.mark.parametrize('order_id,amount,status', [('order-below',499.99,'completed'),('order-boundary',500.0,'completed'),('order-above',500.01,'waiting_approval')])
def test_order_and_refund_share_boundary_facts(order_id, amount, status):
    order = OrderTrackingMock().invoke(request_for('m2.order_tracking', {'order_id': order_id}))
    assert order.data['order_amount'] == amount and type(order.data['order_amount']) is float
    refund = RefundApprovalMock().invoke(request_for('m7.refund_approval', {'order_id': order_id, 'refund_amount': order.data['order_amount'], 'reason': '退货'}))
    assert refund.status == status
    assert refund.data['request_id'].startswith('refund-') and refund.request_id.startswith('req-')
    assert refund.continuation_token is None


@pytest.mark.parametrize('cls,payload', list(zip(MOCK_TYPES,SAMPLES)))
def test_direct_mocks_reject_invalid_input(cls,payload):
    value=cls().invoke(request_for(cls.manifest.capability_id, {}))
    assert value.status == 'failed' and value.error.code == ErrorCode.INVALID_INPUT


def test_trace_serialization_and_generated_ids(registry,load_plan):
    report=Executor(registry).execute(load_plan('operations'))
    assert re.fullmatch('task-[0-9a-f]{12}',report.task_id)
    assert re.fullmatch('trace-[0-9a-f]{16}',report.trace_id)
    requests=set()
    for record in report.steps.values():
        assert re.fullmatch('req-[0-9a-f]{12}',record.request_id)
        requests.add(record.request_id)
        assert record.result.request_id == record.request_id
    assert len(requests)==3
    for event in report.model_dump(mode='json')['events']:
        assert 'timestamp' not in event and 'message' not in event
        assert datetime.fromisoformat(event['ts']).tzinfo is not None
        if event['status'] != 'pending':
            assert event['request_id'] in requests


@pytest.mark.parametrize('week',['2026-41','2026-W1','2026-W00','2026-W54'])
def test_week_format_rejected(registry,week):
    value=registry.get('m6.data_fusion').invoke(request_for('m6.data_fusion',{'week':week}))
    assert value.status=='failed'


def test_error_vocabulary_and_correlation():
    req=request_for('m1.faq_chat',{})
    with pytest.raises(ValidationError):
        ErrorDetail(code='UNLISTED',message='x',task_id=req.task_id,trace_id=req.trace_id)
    err=ErrorDetail(code=ErrorCode.TOOL_UNAVAILABLE,message='offline',task_id=req.task_id,trace_id=req.trace_id,request_id=req.request_id)
    assert err.retryable
    with pytest.raises(ValidationError):
        AgentResult(**req.model_dump(exclude={'payload','context'}),status='failed',error=err.model_copy(update={'request_id':'req-000000000002'}))


@pytest.mark.parametrize('supports,token',[(False,'cont-0000000000000001'),(True,None)])
def test_resume_declaration_checked(registry,load_plan,supports,token):
    from hub_platform.registry import CapabilityRegistry
    class Waiting(RefundApprovalMock):
        def invoke(self,request):
            return super().invoke(request).model_copy(update={'continuation_token':token})
    replacement=CapabilityRegistry()
    for spec in registry.list_capabilities():
        module=registry.get(spec.capability_id)
        if spec.capability_id=='m7.refund_approval':
            spec.supports_resume=supports
            module=Waiting()
        replacement.register(spec,module)
    report=Executor(replacement).execute(load_plan('refund_waiting'))
    assert report.steps['s2'].error.code==ErrorCode.CONTRACT_MISMATCH
