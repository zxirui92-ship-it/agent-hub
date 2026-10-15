"""Shared M7 v2 business schema; resume availability is implementation metadata."""
from common.money import yuan_schema
from common.contracts import CapabilityManifest


def refund_manifest(*, supports_resume=False) -> CapabilityManifest:
    text = {'type': 'string', 'minLength': 1}
    money = yuan_schema()
    def obj(**props):
        return {'type': 'object', 'additionalProperties': False, 'required': list(props), 'properties': props}
    return CapabilityManifest(
        capability_id='m7.refund_approval', version='3.0', name='退款审批流程',
        description='本地订单样例的整单退款流程；不超过 500 元的普通订单自动审核，超过或高风险则等待人工审核；审批不执行打款。',
        input_schema=obj(order_id=text, refund_amount=yuan_schema(0.01), reason=text),
        output_schema=obj(request_id=text,
            approval_status={'type': 'string', 'enum': ['approved', 'rejected', 'waiting_approval']},
            node_trace={'type': 'array', 'items': obj(node_name=text)},
            state_view=obj(order_id=text, order_amount=money, refund_amount=money)),
        preconditions=['refund_amount 必须等于共享订单事实的 order_amount；金额均为元（最多两位小数）'],
        side_effects='requires_approval', execution_mode='may_wait', supports_resume=supports_resume, owner='郑江')
