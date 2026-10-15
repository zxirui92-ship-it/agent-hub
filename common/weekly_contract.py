"""M3 v2: current M6 view in, auditable Plan/Execute steps out."""
from copy import deepcopy
from datetime import timedelta
from common.contracts import CapabilityManifest
from common.iso_week import week_start
from common.promotion_contract import promotion_manifest


def previous_week(week: str) -> str:
    try:
        previous = week_start(week) - timedelta(days=7)
    except OverflowError as exc:
        raise ValueError('上一 ISO 周超出支持的日历范围') from exc
    iso = previous.isocalendar()
    return f'{iso.year:04d}-W{iso.week:02d}'


def validate_periods(payload: dict) -> None:
    week_start(payload['fused_data']['week'])
    previous = payload.get('previous_fused_data')
    if previous is not None:
        week_start(previous['week'])
        if previous['week'] != previous_week(payload['fused_data']['week']):
            raise ValueError('previous_fused_data 必须是相邻上一 ISO 周')


def weekly_manifest() -> CapabilityManifest:
    fused = deepcopy(promotion_manifest().input_schema['properties']['fused_data'])
    text = {'type': 'string', 'minLength': 1}
    return CapabilityManifest(
        capability_id='m3.weekly_report', version='2.0', name='运营周报生成',
        description='先规划再执行，根据 M6 融合数据生成周报；可提供上一周同口径数据计算环比，否则明确标记缺失。',
        input_schema={'type': 'object', 'additionalProperties': False, 'required': ['fused_data'],
                      'properties': {'fused_data': fused, 'previous_fused_data': deepcopy(fused)}},
        output_schema={'type': 'object', 'additionalProperties': False,
            'required': ['week', 'report_markdown', 'steps'], 'properties': {
                'week': fused['properties']['week'], 'report_markdown': text,
                'steps': {'type': 'array', 'minItems': 1, 'items': {
                    'type': 'object', 'additionalProperties': False,
                    'required': ['step_id', 'description', 'status', 'result_summary', 'duration_ms'],
                    'properties': {'step_id': {'type': 'string', 'pattern': '^s[1-9][0-9]*$'},
                        'description': text, 'status': {'type': 'string', 'enum': ['completed']},
                        'result_summary': text, 'duration_ms': {'type': 'integer', 'minimum': 0}}}}}},
        preconditions=['fused_data 为当前平台的完整经营视图，金额为整数分',
                       'previous_fused_data 如提供，必须是相邻上一 ISO 周且使用相同统计口径'],
        side_effects='read_only', execution_mode='immediate', supports_resume=False, owner='邵子谦')
