"""M5 · Multi-Agent 大促方案协同，适配本地公共契约。

Imported from baisumartin/0727-rag_-agent, group_02,
commit 7bcc1c66302a505ed3528456908ab5621c69c79b (agents/multi_agent.py).
Original author: 程炜. Roles, dispatch and aggregation retain the upstream design.
Local migration and contract differences: docs/m5_interface_alignment.md.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable
from uuid import uuid4

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from jsonschema import ValidationError

from common.contracts import AgentRequest, AgentResult, ErrorDetail
from common.errors import ErrorCode, ServiceError
from common.llm import ChatModel
from common.model_config import text_config
from common.money import format_cents
from common.iso_week import week_start
from common.promotion_contract import promotion_manifest
from hub_platform.schema import DataValidator

M5_MODULE = "m5"
M5_CAPABILITY_ID = "m5.promotion_plan"
M5_OWNER = "程炜"
M5_MANIFEST = promotion_manifest()
M5_VERSION = M5_MANIFEST.version
ROLE_PRODUCT, ROLE_OPERATION, ROLE_DATA, ROLE_SERVICE = "product", "operation", "data", "service"
ROLE_LABELS = {ROLE_PRODUCT: "产品", ROLE_OPERATION: "运营", ROLE_DATA: "数据", ROLE_SERVICE: "客服"}
ROLE_ORDER = (ROLE_PRODUCT, ROLE_OPERATION, ROLE_DATA, ROLE_SERVICE)
STEP_AGGREGATE, ROLE_AGGREGATOR = "agg", "aggregator"
LlmFn = Callable[..., str]
LOGGER = logging.getLogger('agent_hub.m5')
StrictValidator = DataValidator


def _public_message(message: str) -> str:
    for name, value in os.environ.items():
        if name.endswith('API_KEY') and value:
            message = message.replace(value, '[redacted]')
    return message[:1000]


def log_event(level: str, module: str, **fields: Any) -> dict[str, Any]:
    record = {'ts': datetime.now(timezone.utc).isoformat(), 'level': level, 'module': module,
              **{key: value for key, value in fields.items() if value is not None}}
    LOGGER.log(logging.ERROR if level == 'error' else logging.INFO, json.dumps(record, ensure_ascii=False))
    return record


def _chat(prompt: str, system: str | None = None) -> str:
    # Same transport/config vocabulary as M4; no dependency on M4 internals.
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    try:
        timeout = float(os.getenv('M5_TIMEOUT_SECONDS') or os.getenv('LLM_TIMEOUT_SECONDS') or '120')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Timeout must be finite and positive')
    except ValueError as exc:
        raise ServiceError(ErrorCode.INVALID_INPUT, 'Invalid M5/LLM timeout configuration', retryable=False) from exc
    config = text_config()
    model = ChatModel(config.base_url, config.api_key, config.model, timeout)
    return model.complete(system or '', prompt)


def _clip(text: str, limit: int = 60) -> str:
    """压成单行并截断，避免破坏 Markdown 表格结构。"""

    flat = " ".join(str(text).split()).replace("|", "/")
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _parse_suggestion(raw: str) -> tuple[str, str]:
    """把角色 Agent 的原始输出拆成 (建议, 依据)。

    解析失败时整段作为建议、依据留空 —— 不抛异常，
    保证协作不会因某个角色输出格式跑偏而整体失败。
    """

    contribution, rationale = "", ""
    for line in str(raw).splitlines():
        for prefix, key in (("建议：", "c"), ("建议:", "c"), ("依据：", "r"), ("依据:", "r")):
            if line.startswith(prefix):
                value = line[len(prefix) :].strip()
                if key == "c":
                    contribution = value
                else:
                    rationale = value
                break

    if not contribution:
        contribution = str(raw).strip()
    return contribution, rationale


def calculated_facts(context: dict[str, Any]) -> list[str]:
    """Calendar and per-order money are computed, never delegated to a model."""
    lines = []
    if context.get('week'):
        start = week_start(context['week'])
        days = [f"{date.fromordinal(start.toordinal() + i).isoformat()}（周{label}）"
                for i, label in enumerate('一二三四五六日')
                if start.toordinal() + i <= date.max.toordinal()]
        lines.append(f"活动周 {context['week']} 日历：" + '、'.join(days) + '。')
    if 'budget_amount' in context:
        amount = context['budget_amount']
        lines.append(f'总预算：{amount} 分 = {format_cents(amount)} 元。')
    fused = context.get('fused_data')
    if fused:
        amount, count = fused['revenue_amount'], fused['order_count']
        lines.append(f"历史统计周 {fused['week']}：成交金额 {amount} 分 = {format_cents(amount)} 元；订单数 {count}。")
        if count:
            # Exact half-up rounding to integer cents without float/Decimal limits.
            average = (2 * amount + count) // (2 * count)
            lines.append(f'客单价（成交金额÷订单数，四舍五入到分）：{average} 分 = {format_cents(average)} 元。')
        else:
            lines.append('客单价：无订单，不可计算，不能填零或推测。')
    return lines


def facts_for_prompt(context: dict[str, Any]) -> str:
    lines = ['金额口径：所有 _amount 原始字段单位都是分，100 分=1 元；禁止把分数值直接当元。',
             '只把下列输入当作事实；角色建议不是事实。未知库存、人力、峰值、成本和 ROI 须标记待确认，建议目标须标记假设。']
    lines.extend(calculated_facts(context))
    lines.append('日历、预算、客单价使用上述程序计算值，不得自行重算或采用角色建议中的矛盾值。'
                 '不要把周订单量当作日订单量；缺少咨询比例不能推算真实咨询峰值。')
    if context.get('week'):
        lines.append(f"目标活动周（以此安排方案时间线）：{context['week']}。")
    if 'budget_amount' in context:
        amount = context['budget_amount']
        lines.append(f'预算：{amount} 分 = {format_cents(amount)} 元。')
    fused = context.get('fused_data')
    if fused:
        amount = fused['revenue_amount']
        lines.append(f"融合数据统计周：{fused['week']}（历史依据，不替代目标活动周）。")
        lines.append(f"成交金额：{amount} 分 = {format_cents(amount)} 元（不是会计收入）。")
        lines.append('完整融合事实：' + json.dumps(fused, ensure_ascii=False))
    if context.get('report_markdown'):
        lines.append('输入周报：' + context['report_markdown'])
    return '\n'.join(lines)


class BaseRoleAgent:
    """专业角色 Agent 的公共骨架：拼 Prompt → 调 LLM → 拆成建议/依据。"""

    role: str = ""
    responsibility: str = ""
    checklist: tuple[str, ...] = ()
    suggestion_hint: str = "具体可执行建议，100 字以内"
    rationale_hint: str = "支撑该建议的数据或理由，50 字以内"

    def __init__(self, llm_fn: LlmFn | None = None) -> None:
        self._llm: LlmFn = llm_fn or _chat

    @property
    def label(self) -> str:
        return ROLE_LABELS[self.role]

    def build_prompt(self, goal: str, context: dict[str, Any]) -> str:
        lines = [
            f"你现在的身份：「{self.label}」。",
            f"你的职责：{self.responsibility}。",
            f"本次大促目标：{goal}",
        ]

        background: list[str] = []
        if context.get("week"):
            background.append(f"周期：{context['week']}")
        if context.get("budget_amount") is not None:
            # 入参单位是「分」，展示时换算成元，避免四个人各写各的单位
            background.append(f"预算：{format_cents(context['budget_amount'])} 元")
        if context.get("report_markdown"):
            background.append(f"运营周报摘要：{_clip(str(context['report_markdown']), 200)}")
        if context.get("fused_data"):
            background.append(f"融合数据摘要：{_clip(str(context['fused_data']), 200)}")
        if background:
            lines.append("已知背景：" + "；".join(background))
        lines.append(facts_for_prompt(context))

        lines.append("你必须重点回答以下问题：")
        lines.extend(f"- {item}" for item in self.checklist)

        lines.append(
            "请给出你的专业判断，严格按两行输出，不要输出任何其他内容：\n"
            f"建议：<{self.suggestion_hint}>\n"
            f"依据：<{self.rationale_hint}>"
        )
        return "\n".join(lines)

    def run(self, goal: str, context: dict[str, Any]) -> dict[str, str]:
        raw = self._llm(self.build_prompt(goal, context))
        if not isinstance(raw, str) or not raw.strip():
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, "Role model returned empty or non-text content")
        contribution, rationale = _parse_suggestion(raw)
        return {"role": self.role, "contribution": contribution, "rationale": rationale}


class ProductAgent(BaseRoleAgent):
    """产品角色：负责选品、定价与库存备货。"""

    role = ROLE_PRODUCT
    responsibility = "负责大促的商品选择、价格带设计与库存备货"
    checklist = (
        "本次大促的选品范围如何界定，引流款与利润款如何搭配",
        "折扣力度与价格带如何设置，是否触碰价格底线",
        "备货量与库存周转如何安排",
    )


class OperationAgent(BaseRoleAgent):
    """运营角色：负责活动节奏、流量与补贴投放。"""

    role = ROLE_OPERATION
    responsibility = "负责大促的活动节奏、流量分配与补贴投放"
    checklist = (
        "活动节奏如何切分（预热 / 爆发 / 返场）",
        "流量与补贴资源如何在各阶段之间分配",
        "需要哪些承接动作来保证转化率",
    )
    suggestion_hint = "具体可执行建议，120 字以内"


class DataAgent(BaseRoleAgent):
    """数据角色：负责口径、预估与监控指标。"""

    role = ROLE_DATA
    responsibility = "负责数据口径统一、效果预估与监控指标设计"
    checklist = (
        "GMV / 转化率 / 客单价的目标如何拆解到各阶段",
        "数据口径与对账方式如何统一",
        "用哪些指标判断大促是否达标、何时触发预警",
    )


class ServiceAgent(BaseRoleAgent):
    """客服角色：负责咨询承接、话术与售后预案。"""

    role = ROLE_SERVICE
    responsibility = "负责大促期间的咨询承接、客服话术与售后风险预案"
    checklist = (
        "预计咨询峰值是多少，人力如何排班",
        "哪些问题会成为高频咨询，话术如何提前准备",
        "退换货与物流异常的风险如何处理",
    )


# =============================================================================
# Orchestrator：拆解 + 分派 + 消息往返
# =============================================================================
class M5Orchestrator:
    """M5 内部协调者：把目标拆给四个角色，并收集回传消息。"""

    def __init__(
        self,
        llm_fn: LlmFn | None = None,
        log_fn: Callable[..., dict[str, Any]] | None = None,
        agents: list[BaseRoleAgent] | None = None,
    ) -> None:
        llm_fn = llm_fn or _chat
        self._log = log_fn or log_event
        self._agents: list[BaseRoleAgent] = agents or [
            ProductAgent(llm_fn),
            OperationAgent(llm_fn),
            DataAgent(llm_fn),
            ServiceAgent(llm_fn),
        ]

    def decompose(self, goal: str, context: dict[str, Any]) -> list[dict[str, Any]]:
        """拆解目标：为每个角色生成一个带 step_id 的子任务。

        四个角色的职责是固定的四类职能，因此拆解规则是确定性的 ——
        这样执行顺序与消息轨迹可复现，便于测试与答辩演示。
        """

        steps: list[dict[str, Any]] = []
        for index, agent in enumerate(self._agents, start=1):
            steps.append(
                {
                    "step_id": f"s{index}",
                    "role": agent.role,
                    "instruction": (
                        f"以「{agent.label}」身份，围绕目标「{goal}」完成："
                        + "；".join(agent.checklist)
                    ),
                }
            )
        return steps

    def dispatch(
        self,
        goal: str,
        context: dict[str, Any],
        log_ctx: dict[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """按拆解结果分派任务，并记录消息派发 / 回传轨迹。

        每次派发与回传各写一条结构化日志（作业 AC-M5-02 的证据来源）。
        """

        base = dict(log_ctx or {})
        contributions: list[dict[str, str]] = []

        for step, agent in zip(self.decompose(goal, context), self._agents):
            # role 为规范 §12 的待补充扩展字段，用于表达角色间的消息传递
            self._log(
                "info",
                M5_MODULE,
                **base,
                step_id=step["step_id"],
                role=agent.role,
                status="running",
            )

            started = time.perf_counter()
            result = agent.run(goal, context)
            duration_ms = int((time.perf_counter() - started) * 1000)

            self._log(
                "info",
                M5_MODULE,
                **base,
                step_id=step["step_id"],
                role=agent.role,
                status="completed",
                duration_ms=duration_ms,
            )
            contributions.append(result)

        return contributions


# =============================================================================
# Aggregator：汇总（关键：不是四段拼接）
# =============================================================================
class Aggregator:
    """把四个角色的产出汇总为一份统一方案。

    输出由两部分组成：
    1. 程序生成的「四方主张对照表」—— 结构化地并置四方观点，天然不是拼接；
    2. LLM 生成的方案正文 —— 被要求点名冲突角色、给出取舍理由、排统一时间线。
    """

    SYSTEM_PROMPT = (
        "你是星潮电商大促方案的总编。你的任务是把四个职能角色的建议"
        "整合成一份可执行的统一方案。"
    )

    def build_skeleton(self, contributions: list[dict[str, str]]) -> str:
        """程序生成的结构化骨架，保证输出至少具备跨角色的对照结构。"""

        lines = ["## 一、四方主张与冲突消解", "", "| 角色 | 核心主张 |", "| --- | --- |"]
        for item in contributions:
            label = ROLE_LABELS.get(item.get("role", ""), item.get("role", ""))
            lines.append(f"| {label} | {_clip(item.get('contribution', ''), 80)} |")
        lines.append("")
        return "\n".join(lines)

    def build_prompt(self, goal: str, contributions: list[dict[str, str]], context=None) -> str:
        blocks: list[str] = []
        for item in contributions:
            label = ROLE_LABELS.get(item.get("role", ""), item.get("role", ""))
            blocks.append(
                f"【{label}】建议：{item.get('contribution', '')}\n依据：{item.get('rationale', '')}"
            )

        return "\n".join(
            [
                f"大促目标：{goal}",
                facts_for_prompt(context or {}),
                "",
                "四个角色各自的建议如下：",
                *blocks,
                "",
                "请产出一份统一的大促方案，必须满足：",
                "1. 先给出四方共识，再整合为统一的执行方案，禁止把四段原文依次罗列；",
                "2. 若四方建议存在冲突（例如预算、折扣力度、人力），必须点名是哪两个角色冲突，"
                "并给出取舍理由；",
                "3. 输出一条覆盖预热、爆发、返场的统一时间线，把四方动作排进同一根时间轴；",
                "4. 直接输出 Markdown 正文，不要解释你的写作过程。",
            ]
        )

    def merge(
        self,
        goal: str,
        contributions: list[dict[str, str]],
        llm_fn: LlmFn | None = None,
        log_fn: Callable[..., dict[str, Any]] | None = None,
        log_ctx: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """生成最终的 plan_markdown。"""

        llm_fn = llm_fn or _chat
        log = log_fn or log_event
        base = dict(log_ctx or {})
        skeleton = self.build_skeleton(contributions)

        # 汇总要生成上千字正文，是整条链路里最慢的一步。
        # 这里必须补日志：此前它没有日志，一旦超时终端上看不出"它在跑"，
        # 只会看到前面的角色都成功、然后突然 failed，极难定位。
        log(
            "info",
            M5_MODULE,
            **base,
            step_id=STEP_AGGREGATE,
            role=ROLE_AGGREGATOR,
            status="running",
        )

        started = time.perf_counter()
        body = llm_fn(self.build_prompt(goal, contributions, context), system=self.SYSTEM_PROMPT)
        if not isinstance(body, str) or not body.strip():
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, "Aggregator returned empty or non-text content")
        duration_ms = int((time.perf_counter() - started) * 1000)

        log(
            "info",
            M5_MODULE,
            **base,
            step_id=STEP_AGGREGATE,
            role=ROLE_AGGREGATOR,
            status="completed",
            duration_ms=duration_ms,
        )

        facts = calculated_facts(context or {})
        verified = ('## 已核对的基础数据\n\n' + '\n'.join('- ' + item for item in facts)
                    + '\n\n') if facts else ''
        return (verified + f"{skeleton}\n"
                '> 以下为模型协作建议；新增目标、投放效果、库存与排班需确认，不代表已执行。\n\n'
                + f"{body.strip()}\n")


# Platform boundary: local AgentRequest / AgentResult, no upstream common copy.
def _failure(request: AgentRequest, code: ErrorCode, message: str, *, retryable=None) -> AgentResult:
    correlation = {key: getattr(request, key) for key in ('request_id', 'task_id', 'trace_id', 'capability_id')}
    error_fields = {key: correlation[key] for key in ('request_id', 'task_id', 'trace_id')}
    if retryable is not None:
        error_fields['retryable'] = retryable
    log_event('error', M5_MODULE, **correlation, status='failed', error_code=code.value)
    return AgentResult(**correlation, status='failed', error=ErrorDetail(
        code=code, message=_public_message(message), **error_fields))


def invoke(request: AgentRequest, llm_fn: LlmFn | None = None) -> AgentResult:
    if request.capability_id != M5_CAPABILITY_ID:
        return _failure(request, ErrorCode.CONTRACT_MISMATCH, 'Request capability_id does not match M5')
    try:
        StrictValidator(M5_MANIFEST.input_schema).validate(request.payload)
    except ValidationError as exc:
        return _failure(request, ErrorCode.INVALID_INPUT, exc.message, retryable=False)
    # All calls use the top-level trace_id; conflicting context metadata cannot replace it.
    payload = request.model_copy(deep=True).payload
    goal = payload['goal'].strip()
    context = {key: payload[key] for key in ('week', 'budget_amount', 'report_markdown', 'fused_data') if key in payload}
    correlation = {key: getattr(request, key) for key in ('request_id', 'task_id', 'trace_id', 'capability_id')}
    try:
        contributions = M5Orchestrator(llm_fn=llm_fn).dispatch(goal, context, correlation)
        plan = Aggregator().merge(goal, contributions, llm_fn=llm_fn, log_ctx=correlation, context=context)
        data = {'plan_markdown': plan, 'roles': contributions}
        StrictValidator(M5_MANIFEST.output_schema).validate(data)
        return AgentResult(**correlation, status='completed', data=data)
    except ServiceError as exc:
        return _failure(request, exc.code, str(exc), retryable=exc.retryable)
    except ValidationError as exc:
        return _failure(request, ErrorCode.CONTRACT_MISMATCH, exc.message, retryable=False)
    except Exception as exc:
        return _failure(request, ErrorCode.INTERNAL_ERROR, f'{type(exc).__name__}: {exc}', retryable=False)


class PromotionAgent:
    """Registry-compatible adapter; injected llm_fn supports offline contract tests."""
    manifest = M5_MANIFEST

    def __init__(self, llm_fn: LlmFn | None = None):
        self.llm_fn = llm_fn

    def invoke(self, request: AgentRequest) -> AgentResult:
        return invoke(request, llm_fn=self.llm_fn)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='M5 four-role promotion planning')
    parser.add_argument('goal', nargs='?')
    parser.add_argument('--week')
    parser.add_argument('--budget-amount', type=int, help='Budget in integer cents')
    parser.add_argument('--report-file', type=Path, help='UTF-8 Markdown report')
    parser.add_argument('--manifest', action='store_true', help='Print contract without invoking the model')
    args = parser.parse_args(argv)
    if args.manifest:
        print(M5_MANIFEST.model_dump_json(indent=2))
        return 0
    if not args.goal:
        parser.error('goal is required')
    payload = {'goal': args.goal}
    for key in ('week', 'budget_amount'):
        if getattr(args, key) is not None:
            payload[key] = getattr(args, key)
    if args.report_file:
        try:
            payload['report_markdown'] = args.report_file.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError):
            parser.error('Cannot read report-file as UTF-8')
    request = AgentRequest(request_id=f'req-{uuid4().hex[:12]}', task_id=f'task-{uuid4().hex[:12]}',
                           trace_id=f'trace-{uuid4().hex[:16]}', capability_id=M5_CAPABILITY_ID, payload=payload)
    response = invoke(request)
    print(response.model_dump_json(indent=2))
    return 0 if response.status == 'completed' else 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    raise SystemExit(main())
