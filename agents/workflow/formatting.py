"""Display helpers kept private to M7; amounts stay in integer cents."""
ORDER_STATUS_LABELS = {'paid': '已支付', 'shipped': '已发货', 'delivered': '已签收',
                       'canceled': '已取消', 'refunded': '已退款', 'not_found': '不存在'}


def label(labels, value):
    return labels.get(value, value or '未知')


def format_amount(value, digits=2):
    return f'{value / 100:.{digits}f} 元'
