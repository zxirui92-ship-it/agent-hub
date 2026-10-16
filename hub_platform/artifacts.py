"""Preserve requested image outputs and explicit, verified business bindings."""
import re

from common.artifact_intent import image_requested
from common.contracts import LiteralBinding, ReferenceBinding
from common.errors import ErrorCode
from common.iso_week import week_start
from hub_platform.errors import HubError


def artifact_requirements(goal, context):
    if not image_requested(goal):
        return None
    requirement = {'output_kind': 'image', 'query': goal}
    if not re.search(r'经营|运营|业绩|成果|战报|成交|销量|销售额|订单量|转化率', goal):
        return requirement
    matches = re.findall(r'(?<!\d)(\d{4})\s*-?\s*[wW]\s*(\d{1,2})(?!\d)', goal)
    weeks = {f'{year}-W{int(number):02d}' for year, number in matches}
    if len(weeks) != 1:
        return requirement
    week = weeks.pop()
    try:
        week_start(week)
    except ValueError:
        return requirement
    requirement['week'] = week
    # Only structured completed M6 results are evidence, never model prose or plans.
    for task in (context or {}).get('history', []):
        for step in (task.get('report') or {}).get('steps', {}).values():
            result = step.get('result') or {}
            facts = (result.get('data') or {}).get('fused_data')
            if (step.get('status') == result.get('status') == 'completed'
                    and result.get('capability_id') == 'm6.data_fusion'
                    and isinstance(facts, dict) and facts.get('week') == week):
                requirement['verified_fused_data'] = facts
    return requirement


def validate_artifact(plan, requirement):
    if requirement is None:
        return
    images = [step for step in plan.steps if step.capability_id == 'm4.capability_gateway'
              and isinstance(step.inputs.get('output_kind'), LiteralBinding)
              and step.inputs['output_kind'].literal == 'image']
    if not images:
        raise HubError(ErrorCode.INVALID_PLAN, '用户要求图片海报，计划必须包含 M4 图片生成步骤，并绑定 output_kind={"literal":"image"}。')
    steps = {step.step_id: step for step in plan.steps}
    for step in images:
        kind, query = step.inputs.get('output_kind'), step.inputs.get('query')
        if not isinstance(kind, LiteralBinding) or kind.literal != 'image':
            raise HubError(ErrorCode.INVALID_PLAN, '图片请求必须显式绑定 output_kind={"literal":"image"}，不得改为 Markdown 或代码。', step.step_id)
        if not isinstance(query, LiteralBinding) or query.literal != requirement['query']:
            raise HubError(ErrorCode.INVALID_PLAN, '图片步骤 query 必须原样保留用户 goal；不得自行增加 Markdown 输出或未提供的业绩主张。', step.step_id)
        if 'week' not in requirement:
            continue
        binding = step.inputs.get('fused_data')
        if isinstance(binding, LiteralBinding):
            if binding.literal == requirement.get('verified_fused_data'):
                continue
        elif isinstance(binding, ReferenceBinding):
            source_id, _, *path = binding.ref.split('.')
            source = steps[source_id]
            week = source.inputs.get('week')
            if (source.capability_id == 'm6.data_fusion' and path == ['fused_data']
                    and isinstance(week, LiteralBinding) and week.literal == requirement['week']):
                continue
        raise HubError(ErrorCode.INVALID_PLAN,
            '经营海报必须绑定 fused_data：原样使用 artifact_requirements.verified_fused_data 的 literal，'
            '或引用本计划中对应周次的 M6 fused_data，并声明依赖；不能只写“根据已有数据”。', step.step_id)
