"""Shared M7 v2 business schema; resume availability is implementation metadata."""
from common.contracts import CapabilityManifest


def refund_manifest(*, supports_resume=False) -> CapabilityManifest:
    text = {'type': 'string', 'minLength': 1}
    money = {'type': 'integer', 'minimum': 0}
    def obj(**props):
        return {'type': 'object', 'additionalProperties': False, 'required': list(props), 'properties': props}
    return CapabilityManifest(
        capability_id='m7.refund_approval', version='2.0', name='退款审批流程',
        description='本地订单样例的整单退款流程；不超过 50000 分自动审核，超过则等待人工审核；审批不执行打款。',
        input_schema=obj(order_id=text, refund_amount={'type': 'integer', 'minimum': 1}, reason=text),
        output_schema=obj(request_id=text,
            approval_status={'type': 'string', 'enum': ['approved', 'rejected', 'waiting_approval']},
            node_trace={'type': 'array', 'items': obj(node_name=text)},
            state_view=obj(order_id=text, order_amount=money, refund_amount=money)),
        preconditions=['refund_amount 必须等于共享订单事实的 order_amount；金额均为整数分'],
        side_effects='requires_approval', execution_mode='may_wait', supports_resume=supports_resume, owner='郑江')
