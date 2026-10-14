"""Shared M1/M2 manifests for implementations and deterministic mocks."""
from common.contracts import CapabilityManifest

TEXT = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
SESSION = {'type': 'string', 'pattern': '^sess-[0-9a-f]{12}$'}
STRINGS = {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}


def obj(**properties):
    return {'type': 'object', 'additionalProperties': False,
            'properties': properties, 'required': list(properties)}


def faq_manifest():
    inputs = obj(question=TEXT, session_id=SESSION)
    inputs['required'] = ['question']
    return CapabilityManifest(capability_id='m1.faq_chat', version='1.1', name='FAQ 客服',
        description='回答服务政策和常见问题，支持 session_id 内的短期多轮记忆；不查询实时订单。',
        input_schema=inputs, output_schema=obj(answer=TEXT, session_id=SESSION),
        preconditions=['question 非空；session_id 如提供须为 sess- 加 12 位小写十六进制'],
        side_effects='read_only', execution_mode='immediate', owner='张新宇')


def order_manifest():
    inputs = obj(order_id=TEXT, query=TEXT)
    inputs['required'] = ['order_id']
    return CapabilityManifest(capability_id='m2.order_tracking', version='1.1', name='订单物流查询',
        description='通过有界 ReAct 查询订单和物流。订单金额来自与退款模块一致的本地订单事实，整数分。',
        input_schema=inputs, output_schema=obj(order_id=TEXT,
            order_amount={'type': 'integer', 'minimum': 0}, order_status=TEXT,
            tracking_number=TEXT, actions=STRINGS, observations=STRINGS, stop_reason=TEXT),
        preconditions=['order_id 必填；query 可补充查询意图，不能覆盖 order_id'],
        side_effects='read_only', execution_mode='immediate', owner='董超')
