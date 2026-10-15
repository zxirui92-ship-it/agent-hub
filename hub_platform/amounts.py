"""Ground a single explicit budget; semantic planning remains the LLM's job.

Only unambiguous Arabic numbers with an explicit CNY unit are interpreted.
Multiple budgets are left to the planner; never silently rewrite a plan.
"""
from decimal import Decimal
import re

from common.contracts import LiteralBinding
from common.money import is_yuan
from common.errors import ErrorCode
from hub_platform.errors import HubError

_BUDGET = re.compile(r'(?:总预算|预算)(?:\s|为|是|设为|改为|改成|调到|调整为|调整到|提高到|降低到|控制在|不超过|上限|[:：])*'
                     r'([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(亿元|万元|块钱|元|分|万|亿|块)')
_UNITS = {'分': Decimal('.01'), '元': 1, '块': 1, '块钱': 1, '万': 10000,
          '万元': 10000, '亿': 100000000, '亿元': 100000000}


def explicit_budget(goal):
    # Conversation marks supplements separately; the latest explicit correction wins.
    for turn in reversed(goal.split('\n补充：')):
        matches = list(_BUDGET.finditer(turn))
        # A bare 万/亿 must not consume the prefix of 万美元/万日元.
        matches = [m for m in matches if not re.match(r'(?:美元|日元|欧元|港元|港币|英镑|韩元|澳元)', turn[m.end():])]
        if not matches:
            # An unparsed correction must not reactivate an obsolete budget.
            if '预算' in turn or re.search(r'[0-9]\s*(?:万元|亿元|元|分|万|亿|块)', turn):
                return None
            continue
        values = [Decimal(m[1].replace(',', '')) * _UNITS[m[2]] for m in matches]
        if len(set(values)) != 1 or not is_yuan(float(values[0])) or values[0] != Decimal(str(float(values[0]))):
            return None
        return {'budget_amount': float(values[0]), 'source_text': matches[-1][0], 'unit': 'CNY_yuan'}
    return None


def validate_budget(plan, registry, fact):
    if fact is None:
        return
    consumers = [step for step in plan.steps if 'budget_amount' in
                 registry.get_manifest(step.capability_id).input_schema['properties']]
    # A multi-plan budget allocation needs semantic interpretation, not copying
    # the full total into every child plan.
    if len(consumers) != 1:
        return
    step = consumers[0]
    binding = step.inputs.get('budget_amount')
    if not isinstance(binding, LiteralBinding) or binding.literal != fact['budget_amount']:
        raise HubError(ErrorCode.INVALID_PLAN,
                       f"显式预算 {fact['source_text']} 应为 {fact['budget_amount']} 元；"
                       'budget_amount 必须使用此金额 literal，不可遗漏或改变单位。', step.step_id)
