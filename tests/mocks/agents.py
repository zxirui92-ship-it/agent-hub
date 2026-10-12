"""Deterministic business fixtures, not real implementations of seven architectures."""
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from common.contracts import AgentRequest, AgentResult, CapabilityManifest, ErrorDetail
from common.errors import ErrorCode
from common.gateway_contract import gateway_manifest
from hub_platform.errors import HubError
from hub_platform.registry import CapabilityRegistry
from hub_platform.schema import validate_data


def obj(**properties: Any) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


STRING = {"type": "string", "minLength": 1}
STRINGS = {"type": "array", "items": STRING}
WEEK = {"type": "string", "pattern": r"^[0-9]{4}-W(0[1-9]|[1-4][0-9]|5[0-3])$"}
MONEY = {"type": "integer", "minimum": 0}
FUSED = obj(week=WEEK, revenue_amount=MONEY, order_count={"type": "integer", "minimum": 0},
            conversion_rate={"type": "number", "minimum": 0, "maximum": 1}, anomaly=STRING)
ORDER = obj(order_id=STRING, order_amount=MONEY, order_status=STRING, tracking_number=STRING,
            actions=STRINGS, observations=STRINGS, stop_reason=STRING)
OWNERS = dict(zip([f"m{i}" for i in range(1, 8)], ["张新宇", "董超", "邵子谦", "张熙睿", "程炜", "奉逸飞", "郑江"]))


def manifest(capability_id: str, name: str, description: str,
             inputs: dict[str, Any], outputs: dict[str, Any], *, waiting: bool = False) -> CapabilityManifest:
    return CapabilityManifest(
        capability_id=capability_id, version="1.0", name=name,
        description=description, input_schema=inputs, output_schema=outputs,
        preconditions=list(inputs["required"]),
        side_effects="requires_approval" if waiting else "read_only",
        execution_mode="may_wait" if waiting else "immediate", supports_resume=False,
        owner=OWNERS.get(capability_id.split('.')[0], "测试维护者"),
    )


def result(request: AgentRequest, data: dict[str, Any], **kwargs: Any) -> AgentResult:
    return AgentResult(request_id=request.request_id, task_id=request.task_id,
                       trace_id=request.trace_id, capability_id=request.capability_id,
                       data=data, **{"status": "completed", **kwargs})


def failure(request: AgentRequest, code: ErrorCode, message: str) -> AgentResult:
    return result(request, {}, status="failed", error=ErrorDetail(
        code=code, message=message, trace_id=request.trace_id, task_id=request.task_id,
        request_id=request.request_id))


def order_fact(order_id: str) -> dict:
    # Both M2 and M7 read the same immutable source, returning fresh data each call.
    orders = json.loads((Path(__file__).resolve().parents[2] / "data/fixtures/order_basic.json").read_text(encoding="utf-8"))
    if order_id == "unavailable":
        raise HubError(ErrorCode.TOOL_UNAVAILABLE, "Mock 订单服务暂不可用")
    if order_id not in orders:
        raise HubError(ErrorCode.NOT_FOUND, f"订单不存在：{order_id}")
    return orders[order_id]


class ValidatedMock:
    def invoke(self, request: AgentRequest) -> AgentResult:
        try:
            if request.capability_id != self.manifest.capability_id:
                raise HubError(ErrorCode.CONTRACT_MISMATCH, "Wrong capability_id")
            validate_data(request.payload, self.manifest.input_schema, ErrorCode.INVALID_INPUT)
            return self._invoke(request.model_copy(deep=True))
        except HubError as exc:
            return failure(request, exc.code, str(exc))


class FAQMock(ValidatedMock):
    manifest = manifest("m1.faq_chat", "FAQ 答复（Mock）", "固定七天退货政策。",
                        obj(question=STRING), obj(answer=STRING, session_id={"type": "string", "pattern": "^sess-[0-9a-f]{12}$"}))

    def _invoke(self, request):
        return result(request, {"answer": "Mock 政策：符合条件的商品支持七天无理由退货。",
                                "session_id": "sess-000000000001"})


class OrderTrackingMock(ValidatedMock):
    manifest = manifest("m2.order_tracking", "订单物流（Mock）", "查询共享订单事实，金额为整数分。", obj(order_id=STRING), ORDER)

    def _invoke(self, request):
        order_id = request.payload["order_id"]
        fact = order_fact(order_id)
        return result(request, {"order_id": order_id, **fact, "actions": ["query_order", "query_logistics"],
            "observations": [f"Mock 订单金额 {fact['order_amount']} 分", "Mock 物流运输中"], "stop_reason": "查询完成"})


class WeeklyReportMock(ValidatedMock):
    manifest = manifest("m3.weekly_report", "运营周报（Mock）", "根据传入经营视图生成固定周报。",
                        obj(fused_data=FUSED), obj(week=WEEK, report_markdown=STRING, steps=STRINGS))

    def _invoke(self, request):
        data = request.payload["fused_data"]
        return result(request, {"week": data["week"], "report_markdown": (
            f"# {data['week']} 运营周报（Mock）\n销售额：{data['revenue_amount']} 分；"
            f"订单：{data['order_count']}；转化率：{data['conversion_rate']}。\n异常：{data['anomaly']}。"
        ), "steps": ["读取经营视图（Mock）", "生成固定格式报告（Mock）"]})


class GatewayMock(ValidatedMock):
    manifest = gateway_manifest()

    def _invoke(self, request):
        return result(request, {"skill_name": "kb_qa", "result": "Mock 知识条目：大促优惠不得重复叠加。",
                                "route_reason": "确定性 Mock，不执行真实语义路由或 Skill。"})


class PromotionPlanMock(ValidatedMock):
    manifest = manifest("m5.promotion_plan", "大促策划（Mock）", "以传入周报为依据生成固定方案。",
                        obj(report=STRING), obj(plan_markdown=STRING, source_report=STRING,
                        roles=obj(product=STRING, operations=STRING, data=STRING, service=STRING)))

    def _invoke(self, request):
        return result(request, {"plan_markdown": "Mock 方案：针对转化下降，进行老客优惠券小规模试投。",
                                "source_report": request.payload["report"],
                                "roles": {"product": "选品", "operations": "配置优惠券", "data": "观察转化率", "service": "发布政策 FAQ"}})


class DataFusionMock(ValidatedMock):
    manifest = manifest("m6.data_fusion", "经营融合（Mock）", "固定订单、行为、营销口径的经营视图。",
                        obj(week=WEEK), obj(fused_data=FUSED, field_definitions=STRINGS, update_events=STRINGS))

    def _invoke(self, request):
        return result(request, {"fused_data": {"week": request.payload["week"], "revenue_amount": 12000000,
            "order_count": 800, "conversion_rate": 0.032, "anomaly": "转化率环比下降 0.5 个百分点"},
            "field_definitions": ["revenue_amount：销售额，整数分", "order_count：订单数量", "conversion_rate：转化率"],
            "update_events": ["Mock 订单读取", "Mock 行为与营销数据融合"]})


class RefundApprovalMock(ValidatedMock):
    manifest = manifest("m7.refund_approval", "退款审批（Mock）", "整单退款校验；不超过 50000 分自动通过，否则等待，无恢复。",
                        obj(order_id=STRING, refund_amount={"type": "integer", "minimum": 1}, reason=STRING),
                        obj(request_id=STRING, approval_status={"type": "string", "enum": ["approved", "waiting_approval"]},
                            node_trace={"type": "array", "items": obj(node_name=STRING)},
                            state_view=obj(order_id=STRING, order_amount=MONEY, refund_amount=MONEY)), waiting=True)

    def _invoke(self, request):
        payload = request.payload
        fact = order_fact(payload["order_id"])
        if type(payload["refund_amount"]) is not int or payload["refund_amount"] != fact["order_amount"]:
            raise HubError(ErrorCode.INVALID_INPUT, "Mock 仅支持整单退款；refund_amount 必须等于共享订单事实 order_amount")
        waiting = fact["order_amount"] > 50000
        data = {"request_id": "refund-" + sha256(request.request_id.encode()).hexdigest()[:12],
                "approval_status": "waiting_approval" if waiting else "approved",
                "node_trace": [{"node_name": "accept"}, {"node_name": "manual_review" if waiting else "auto_approve"}],
                "state_view": {"order_id": payload["order_id"], "order_amount": fact["order_amount"], "refund_amount": payload["refund_amount"]}}
        return result(request, data, status="waiting_approval" if waiting else "completed",
                      waiting_reason="金额超过 50000 分，等待人工审核；本阶段不支持恢复。" if waiting else None)


MOCK_TYPES = (FAQMock, OrderTrackingMock, WeeklyReportMock, GatewayMock, PromotionPlanMock, DataFusionMock, RefundApprovalMock)


def create_mock_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for mock_type in MOCK_TYPES:
        registry.register(mock_type.manifest, mock_type())
    return registry
