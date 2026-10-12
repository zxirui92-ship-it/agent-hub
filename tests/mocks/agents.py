"""Seven independently callable mocks; only the demo composition root imports them."""
from typing import Any

from common.contracts import AgentRequest, AgentResult, CapabilityManifest, ErrorDetail
from hub_platform.registry import CapabilityRegistry


def obj(**properties: Any) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


STRING = {"type": "string", "minLength": 1}
MONEY = {"type": "number", "minimum": 0}
FUSED = obj(week=STRING, revenue=MONEY, orders={"type": "integer", "minimum": 0},
            conversion_rate={"type": "number", "minimum": 0, "maximum": 1},
            anomaly=STRING)
ORDER = obj(order_id=STRING, amount=MONEY, order_status=STRING, logistics_status=STRING)


def manifest(capability_id: str, name: str, description: str,
             inputs: dict[str, Any], outputs: dict[str, Any], *, waiting: bool = False) -> CapabilityManifest:
    return CapabilityManifest(
        capability_id=capability_id, version="0.1.0-candidate", name=name,
        description=description, input_schema=inputs, output_schema=outputs,
        preconditions=list(inputs["required"]),
        side_effects="requires_approval" if waiting else "read_only",
        execution_mode="may_wait" if waiting else "immediate", supports_resume=False,
        owner=f"{capability_id.split('.')[0].upper()} module owner (pending assignment)",
    )


def result(request: AgentRequest, data: dict[str, Any], **kwargs: Any) -> AgentResult:
    return AgentResult(request_id=request.request_id, task_id=request.task_id,
                       trace_id=request.trace_id, capability_id=request.capability_id,
                       data=data, **{"status": "completed", **kwargs})


def failure(request: AgentRequest, code: str, message: str) -> AgentResult:
    return result(request, {}, status="failed", error=ErrorDetail(
        code=code, message=message, trace_id=request.trace_id, task_id=request.task_id))


class FAQMock:
    manifest = manifest("m1.faq", "FAQ 答复（Mock）", "返回固定的七天退货政策说明。",
                        obj(question=STRING), obj(answer=STRING, policy_id=STRING))

    def invoke(self, request: AgentRequest) -> AgentResult:
        return result(request, {"answer": "Mock 政策：符合条件的商品支持七天无理由退货。",
                                "policy_id": "RETURN-7D"})


class OrderTrackingMock:
    manifest = manifest("m2.order_tracking", "订单物流（Mock）", "查询固定样例订单的金额、订单及物流状态。",
                        obj(order_id=STRING), ORDER)

    def invoke(self, request: AgentRequest) -> AgentResult:
        order_id = request.payload["order_id"]
        if order_id == "unavailable":
            return failure(request, "TOOL_UNAVAILABLE", "Mock 订单服务暂不可用")
        orders = {"2025101234": 699.0, "ORDER-LOW": 199.0}
        if order_id not in orders:
            return failure(request, "NOT_FOUND", f"订单不存在：{order_id}")
        return result(request, {"order_id": order_id, "amount": orders[order_id],
                                "order_status": "paid", "logistics_status": "in_transit"})


class WeeklyReportMock:
    manifest = manifest("m3.weekly_report", "运营周报（Mock）", "根据传入经营视图生成固定格式周报。",
                        obj(fused_data=FUSED), obj(report_markdown=STRING))

    def invoke(self, request: AgentRequest) -> AgentResult:
        data = request.payload["fused_data"]
        return result(request, {"report_markdown": (
            f"# {data['week']} 运营周报（Mock）\n销售额：{data['revenue']}；"
            f"订单：{data['orders']}；转化率：{data['conversion_rate']}。\n异常：{data['anomaly']}。"
        )})


class GatewayMock:
    manifest = manifest("m4.capability_gateway", "能力网关（Mock）", "返回固定知识库条目及来源，不调用实际 Skill。",
                        obj(query=STRING), obj(skill=STRING, answer=STRING, source=STRING))

    def invoke(self, request: AgentRequest) -> AgentResult:
        return result(request, {"skill": "knowledge_base", "answer": "大促优惠不得重复叠加（模拟条目）。",
                                "source": "fixture://policies/promotion"})


class PromotionPlanMock:
    manifest = manifest("m5.promotion_plan", "大促策划（Mock）", "以传入周报为依据，输出固定结构的大促方案。",
                        obj(report=STRING), obj(proposal=STRING, source_report=STRING,
                        responsibilities=obj(product=STRING, operations=STRING, data=STRING, service=STRING)))

    def invoke(self, request: AgentRequest) -> AgentResult:
        return result(request, {"proposal": "Mock 方案：针对转化下降，进行老客优惠券小规模试投。",
                                "source_report": request.payload["report"],
                                "responsibilities": {"product": "选品", "operations": "配置优惠券",
                                                     "data": "观察转化率", "service": "发布政策 FAQ"}})


class DataFusionMock:
    manifest = manifest("m6.data_fusion", "经营融合（Mock）", "返回固定订单、行为、营销口径的经营视图。",
                        obj(week=STRING), obj(fused_data=FUSED, sources={"type": "array", "items": STRING}))

    def invoke(self, request: AgentRequest) -> AgentResult:
        return result(request, {"fused_data": {"week": request.payload["week"], "revenue": 120000.0,
                                "orders": 800, "conversion_rate": 0.032, "anomaly": "转化率环比下降 0.5 个百分点"},
                                "sources": ["orders_fixture", "behavior_fixture", "marketing_fixture"]})


class RefundApprovalMock:
    manifest = manifest("m7.refund_approval", "退款审批（Mock）", "金额不超过 500 自动通过；更高金额返回等待人工审核。",
                        obj(order_id=STRING, amount={"type": "number", "minimum": 0.01}, reason=STRING),
                        obj(application_id=STRING, order_id=STRING, amount=MONEY,
                            decision={"type": "string", "enum": ["approved", "pending_review"]}), waiting=True)

    def invoke(self, request: AgentRequest) -> AgentResult:
        waiting = request.payload["amount"] > 500
        data = {"application_id": f"REFUND-{request.payload['order_id']}",
                "order_id": request.payload["order_id"], "amount": request.payload["amount"],
                "decision": "pending_review" if waiting else "approved"}
        return result(request, data, status="waiting_approval" if waiting else "completed",
                      waiting_reason="金额超过 500，等待人工审核；本阶段不支持恢复。" if waiting else None)


MOCK_TYPES = (FAQMock, OrderTrackingMock, WeeklyReportMock, GatewayMock,
              PromotionPlanMock, DataFusionMock, RefundApprovalMock)


def create_mock_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for mock_type in MOCK_TYPES:
        registry.register(mock_type.manifest, mock_type())
    return registry
