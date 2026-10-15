"""Display helpers kept private to M7; amounts stay in integer cents."""
from common.money import format_cents

ORDER_STATUS_LABELS = {'paid': '已支付', 'shipped': '已发货', 'delivered': '已签收',
                       'completed': '已完成', 'pending_payment': '待付款', 'refunding': '退款中',
                       'canceled': '已取消', 'refunded': '已退款', 'not_found': '不存在'}


def label(labels, value):
    return labels.get(value, value or '未知')


def format_amount(value, digits=2):
    # Even compact threshold labels must not round 500.01 down to 500.
    text = format_cents(value)
    return (text[:-3] if digits == 0 and value % 100 == 0 else text) + ' 元'
