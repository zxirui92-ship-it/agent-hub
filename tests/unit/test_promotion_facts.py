"""Regression for dates and tenfold AOV errors found in real Qwen output."""
import pytest

from agents.multi_agent import PromotionAgent, calculated_facts
from tests.contract.test_contracts import request_for


@pytest.mark.parametrize('revenue,count,expected', [
    (1268000000, 66200, '19154 分 = 191.54 元'),
    (1, 2, '1 分 = 0.01 元'),
    (1, 3, '0 分 = 0.00 元'),
    (0, 0, '无订单，不可计算'),
    (10**40 + 1, 1, str(10**40 + 1) + ' 分'),
])
def test_exact_per_order_amount(revenue, count, expected):
    facts = calculated_facts({'fused_data': {'week':'2025-W41',
                             'revenue_amount':revenue, 'order_count':count}})
    assert expected in facts[-1]


@pytest.mark.parametrize('week,monday,sunday', [
    ('2025-W42', '2025-10-13', '2025-10-19'),
    ('2020-W53', '2020-12-28', '2021-01-03'),
])
def test_iso_calendar_crosses_year_correctly(week, monday, sunday):
    calendar = calculated_facts({'week':week})[0]
    assert monday + '（周一）' in calendar
    assert sunday + '（周日）' in calendar


def test_facts_reach_every_role_aggregator_and_public_output():
    prompts = []
    def model(prompt, system=None):
        prompts.append(prompt)
        return '统一建议正文' if system else '建议：先核对库存\n依据：库存待确认'
    result = PromotionAgent(model).invoke(request_for('m5.promotion_plan', {
        'goal':'规划下周促销', 'week':'2025-W42', 'budget_amount':1000000,
        'fused_data': {'week':'2025-W41', 'revenue_amount':1268000000,
            'order_count':66200, 'conversion_rate':.1403, 'anomaly':'无异常'},
    }))
    assert result.status == 'completed'
    assert len(prompts) == 5
    for text in [*prompts, result.data['plan_markdown']]:
        assert '19154 分 = 191.54 元' in text
        assert '2025-10-13（周一）' in text
        assert '1000000 分 = 10000.00 元' in text
    assert len(result.data['roles']) == 4
    assert '统一建议正文' in result.data['plan_markdown']
