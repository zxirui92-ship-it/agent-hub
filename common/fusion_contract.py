"""M6's exported view shared with report/promotion consumers."""
from common.contracts import CapabilityManifest


def fused_schema():
    properties = {
        'week': {'type': 'string', 'pattern': r'^[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])$'},
        'revenue_amount': {'type': 'integer', 'minimum': 0},
        'order_count': {'type': 'integer', 'minimum': 0},
        'conversion_rate': {'type': 'number', 'minimum': 0, 'maximum': 1},
        'anomaly': {'type': 'string', 'minLength': 1},
    }
    return {'type': 'object', 'additionalProperties': False,
            'required': list(properties), 'properties': properties}


def fusion_manifest():
    fused = fused_schema()
    strings = {'type': 'array', 'items': {'type': 'string', 'minLength': 1}}
    return CapabilityManifest(capability_id='m6.data_fusion', version='1.0', name='经营数据融合',
        description='私有黑板融合订单周汇总、行为、营销样例，输出同口径经营视图及来源/缺口；非实时数据。',
        input_schema={'type': 'object', 'additionalProperties': False, 'required': ['week'],
                      'properties': {'week': fused['properties']['week']}},
        output_schema={'type': 'object', 'additionalProperties': False,
            'required': ['fused_data', 'field_definitions', 'update_events'],
            'properties': {'fused_data': fused, 'field_definitions': strings, 'update_events': strings}},
        preconditions=['week 对应可用的 ISO 周样例'], side_effects='read_only',
        execution_mode='immediate', owner='奉逸飞')
