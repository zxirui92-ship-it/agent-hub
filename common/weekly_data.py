"""Shared business calculations; no dependency on any Agent implementation."""


def campaign_summary(orders, campaigns):
    limitation = '未提供活动实际支出及归因成交额，无法计算 ROI；活动预算不作为支出。'
    if campaigns and all('cost_amount' in c and 'gmv_amount' in c for c in campaigns):
        ratios = [c['name'] + '：' + (f"{c['gmv_amount']/c['cost_amount']:.4f}" if c['cost_amount'] else '成本为零不计算') for c in campaigns]
        limitation = '活动成交额/成本：' + '、'.join(ratios) + '；不是利润 ROI。活动与周广告成本统计范围不同，不强行对账。'
    return {'week':orders['week'], 'campaigns':campaigns, 'limitation':limitation}


def insight_summary(order, behavior, marketing):
    notes = [a['reason'] for a in order.get('anomalies', [])]
    if all(k in behavior for k in ('uv', 'detail_uv', 'cart_uv', 'order_uv')):
        notes.append(f"漏斗 UV/详情/加购/下单人数：{behavior['uv']}/{behavior['detail_uv']}/{behavior['cart_uv']}/{behavior['order_uv']}；下单人数/UV 转化率 {behavior['conversion_rate']:.2%}。")
    else:
        notes.append(f"行为源转化率 {behavior['conversion_rate']:.2%}；未提供完整漏斗，无法判断加购瓶颈。")
    notes.append(f"退款率 {order['refund_rate']:.2%}。")
    if marketing['campaigns']:
        notes.append('同期活动：' + '、'.join(c['name'] for c in marketing['campaigns']) + '；仅为同期记录，不证明因果关系。')
    else:
        notes.append('营销样例未记录本周活动，不代表生产环境没有活动。')
    notes.append(marketing['limitation'])
    return {'week':order['week'], 'insights':notes}


def fused_view(week, orders, behavior, insight):
    return {'week':week, 'revenue_amount':orders['gmv_amount'], 'order_count':orders['order_count'],
            'conversion_rate':behavior['conversion_rate'], 'anomaly':'；'.join(insight['insights'])}


def load_business_view(source, week):
    snapshot = source.load(week)
    orders, behavior = snapshot['orders'], snapshot['behavior']
    marketing = campaign_summary(orders, snapshot['campaigns'])
    return fused_view(week, orders, behavior, insight_summary(orders, behavior, marketing))
