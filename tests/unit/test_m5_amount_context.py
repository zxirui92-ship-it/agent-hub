from agents.multi_agent import facts_for_prompt, DataAgent, Aggregator


def test_all_roles_and_aggregator_receive_authoritative_cents_and_full_limitations():
    context = {'budget_amount': 10000000, 'fused_data': {
        'week': '2026-W41', 'revenue_amount': 1268430000, 'order_count': 84562,
        'conversion_rate': 0.0242, 'anomaly': 'x' * 250 + '没有实际营销成本，不能计算 ROI'}}
    role = DataAgent().build_prompt('制定方案', context)
    aggregate = Aggregator().build_prompt('制定方案', [], context)
    for prompt in (role, aggregate):
        assert '1268430000 分 = 12684300.00 元' in prompt
        assert '10000000 分 = 100000.00 元' in prompt
        assert '没有实际营销成本，不能计算 ROI' in prompt
        assert '角色建议不是事实' in prompt


def test_cent_conversion_does_not_round_integer_cents():
    assert '101 分 = 1.01 元' in facts_for_prompt({'budget_amount': 101})
