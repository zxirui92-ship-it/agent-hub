"""离线演示用的确定性 Planner。

仅当显式使用 --offline 时使用。它返回一个符合
PlannerDecision Schema 的 JSON，仍走真实的 PlanValidator / Executor 路径，
因此七个 Mock 模块会被真正执行，前端可以离线看到完整的状态流转。

仅覆盖 frontend_handoff.md 中列出的演示场景；其它目标返回 unsupported。
真实规划请配置 LLM 后使用 DynamicPlanner。
"""
import json
import re


_ORDER = re.compile(r'(20\d{8})')
_WEEK = re.compile(r'(\d{4})-W([0-4]?\d)')
_BUDGET_YUAN = re.compile(r'(\d+(?:\.\d+)?)\s*万元')
_BUDGET_FEN = re.compile(r'(\d+(?:\.\d+)?)\s*元')


def _literal(value):
    return {"literal": value}


def _ref(path):
    return {"ref": path}


def _step(step_id, capability_id, inputs, depends_on=None):
    return {
        "step_id": step_id,
        "capability_id": capability_id,
        "depends_on": depends_on or [],
        "inputs": inputs,
    }


def _detect_week(goal):
    match = _WEEK.search(goal)
    if match:
        year, week = match.group(1), match.group(2)
        return f"{year}-W{int(week):02d}"
    return None


def _detect_budget_yuan(goal):
    from hub_platform.amounts import explicit_budget
    fact = explicit_budget(goal)
    return fact['budget_amount'] if fact else None


class FakePlannerModel:
    """满足 TextModel.complete 接口的确定性规划替身。"""

    def complete(self, system: str, query: str) -> str:
        try:
            data = json.loads(query)
        except (ValueError, TypeError):
            return json.dumps({"status": "unsupported",
                               "message": "离线演示无法解析请求。", "steps": []},
                              ensure_ascii=False)
        goal = (data.get("goal") or "").strip()
        return json.dumps(self._plan(goal), ensure_ascii=False)

    def _clarify(self, message):
        return {"status": "needs_clarification", "message": message, "steps": []}

    def _plan(self, goal: str) -> dict:
        if not goal:
            return self._clarify("请输入任务目标。")

        # 意图判定只看最新一条补充消息，避免历史上下文污染（例如计划预览后另起目标）。
        latest = goal.split("\n补充：")[-1]
        order_id = _ORDER.search(latest)
        order_id = order_id.group(1) if order_id else None
        week = _detect_week(latest) or _detect_week(goal)

        # 退款：需要订单号
        if "退款" in goal or "退钱" in goal:
            if not order_id:
                return self._clarify("退款需要订单号，请补充订单号（例如 2025100004）。")
            return {
                "status": "ready",
                "message": "离线演示计划：先查询订单事实，再发起整单退款。",
                "steps": [
                    _step("s1", "m2.order_tracking", {"order_id": _literal(order_id)}),
                    _step("s2", "m7.refund_approval", {
                        "order_id": _ref("s1.data.order_id"),
                        "refund_amount": _ref("s1.data.order_amount"),
                        "reason": _literal("用户申请整单退款"),
                    }, depends_on=["s1"]),
                ],
            }

        # 周报 + 大促：经营链
        if ("周报" in goal or "经营" in goal) and ("大促" in goal or "促销" in goal or "方案" in goal):
            if not week:
                return self._clarify("请指明要融合的 ISO 周（例如 2025-W41）。")
            budget = _detect_budget_yuan(goal)
            m5_inputs = {"goal": _literal(goal),
                         "report_markdown": _ref("s2.data.report_markdown")}
            if week:
                m5_inputs["week"] = _literal(week)
            if budget is not None:
                m5_inputs["budget_amount"] = _literal(budget)
            return {
                "status": "ready",
                "message": "离线演示计划：融合数据 → 生成周报 → 制定大促方案。",
                "steps": [
                    _step("s1", "m6.data_fusion", {"week": _literal(week)}),
                    _step("s2", "m3.weekly_report",
                          {"fused_data": _ref("s1.data.fused_data")}, depends_on=["s1"]),
                    _step("s3", "m5.promotion_plan", m5_inputs, depends_on=["s2"]),
                ],
            }

        # 订单 / 物流查询
        if order_id or "物流" in goal or "订单" in goal:
            if not order_id:
                return self._clarify("请补充订单号（例如 2025101234）。")
            return {
                "status": "ready",
                "message": "离线演示计划：查询订单与物流。",
                "steps": [_step("s1", "m2.order_tracking", {"order_id": _literal(order_id)})],
            }

        # M4 能力网关：搜索 / 知识库 / 代码 / 图片
        if any(k in goal for k in ("搜索", "查一下", "知识库", "代码", "生成图片", "画", "图片", "写一段")):
            return {
                "status": "ready",
                "message": "离线演示计划：调用能力网关（Mock 固定返回知识库问答）。",
                "steps": [_step("s1", "m4.capability_gateway", {"query": _literal(goal)})],
            }

        # FAQ 客服
        if any(k in goal for k in ("?", "？", "保修", "退货", "政策", "怎么", "什么", "如何", "多久")):
            return {
                "status": "ready",
                "message": "离线演示计划：FAQ 客服问答。",
                "steps": [_step("s1", "m1.faq_chat", {"question": _literal(goal)})],
            }

        return {
            "status": "unsupported",
            "message": ("离线演示仅覆盖 FAQ 客服、订单物流、经营周报+大促、整单退款与能力网关四类场景；"
                        "真实语义规划请配置 LLM。"),
            "steps": [],
        }


def build_offline_planner(registry, max_steps=32):
    """返回一个使用 FakePlannerModel 的 DynamicPlanner。"""
    from hub_platform.planner import DynamicPlanner
    return DynamicPlanner(registry, FakePlannerModel(), max_steps=max_steps)
