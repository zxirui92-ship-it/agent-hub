"""Local fixture order source shared by M2 (real/Mock) and the M7 workflow."""
from importlib.resources import files
from common.errors import ErrorCode, ServiceError
from common.json_data import strict_json_loads

ORDER_PATH = files('common').joinpath('fixtures', 'order_basic.json')


def order_fact(order_id: str) -> dict:
    if order_id == 'unavailable':
        raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, '本地订单服务暂不可用')
    try:
        orders = strict_json_loads(ORDER_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, '无法读取本地订单数据') from exc
    if order_id not in orders:
        raise ServiceError(ErrorCode.NOT_FOUND, f'订单不存在：{order_id}', retryable=False)
    return orders[order_id]
