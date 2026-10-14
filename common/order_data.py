"""Local fixture order source shared by M2 (real/Mock) and the M7 workflow."""
import json
from pathlib import Path
from common.errors import ErrorCode, ServiceError

ORDER_PATH = Path(__file__).resolve().parents[1] / 'data/fixtures/order_basic.json'


def order_fact(order_id: str) -> dict:
    if order_id == 'unavailable':
        raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, '本地订单服务暂不可用')
    try:
        orders = json.loads(ORDER_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ServiceError(ErrorCode.TOOL_UNAVAILABLE, '无法读取本地订单数据') from exc
    if order_id not in orders:
        raise ServiceError(ErrorCode.NOT_FOUND, f'订单不存在：{order_id}', retryable=False)
    return orders[order_id]
