"""Shared M1/M2 manifests for implementations and deterministic mocks."""
from common.contracts import CapabilityManifest

TEXT = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
SESSION = {'type': 'string', 'pattern': '^sess-[0-9a-f]{12}$'}
STRINGS = {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}
LOGISTICS_FIELDS = {
    'logistics_availability': {'type': 'string', 'enum': ['available', 'unavailable', 'inconsistent']},
    'warnings': STRINGS,
}


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
    outputs = obj(order_id=TEXT,
            order_amount={'type': 'integer', 'minimum': 0}, order_status=TEXT,
            tracking_number={'type': 'string'}, actions=STRINGS, observations=STRINGS, stop_reason=TEXT)
    outputs['properties'].update(LOGISTICS_FIELDS)
    return CapabilityManifest(capability_id='m2.order_tracking', version='1.2', name='订单物流查询',
        description='通过有界 ReAct 查询订单和物流，金额为整数分；物流缺失或冲突时仍返回已核实订单事实，运单为空并明确给出物流状态与提示。',
        input_schema=inputs, output_schema=outputs,
        preconditions=['order_id 必填；query 可补充查询意图，不能覆盖 order_id'],
        side_effects='read_only', execution_mode='immediate', owner='董超')
