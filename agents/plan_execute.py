"""M3 Plan & Execute, adapted from the supplied 邵子谦 module.

Planner/Executor/PlanStep remain separate. The platform consumes the flat M6
view; standalone sample loading is explicit and never mixed into M6 results.
See docs/m3_m7_integration.md for source provenance and contract migration.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass, asdict
from importlib.resources import files
import os
from pathlib import Path
import time
from uuid import uuid4

from dotenv import load_dotenv
from common.contracts import AgentRequest, AgentResult
from common.errors import ErrorCode, ServiceError
from common.model_config import text_config
from common.llm import ChatModel, TextModel, json_object
from common.module_boundary import result_for, failure
from common.iso_week import week_start
from common.json_data import strict_json_loads
from common.money import format_yuan
from common.weekly_contract import weekly_manifest, validate_periods, previous_week as _previous_week
from hub_platform.errors import HubError
from hub_platform.schema import validate_data

CAPABILITY_ID = 'm3.weekly_report'
MANIFEST = weekly_manifest()
FIXTURES = files('common').joinpath('fixtures', 'm3')
ACTIONS = {'fetch': '读取融合经营数据', 'compare': '计算同口径环比',
           'anomaly': '分析输入异常', 'report': '汇总 Markdown 周报'}


def _calc_change(current: int | float, previous: int | float) -> float | None:
    return (current - previous) / previous if previous else None


@dataclass
class PlanStep:
    step_id: str
    description: str
    action: str
    status: str = 'pending'
    result_summary: str = ''
    duration_ms: int = 0

    def to_dict(self):
        return {key: value for key, value in asdict(self).items() if key != 'action'}


class WeeklyReportPlanner:
    """Plans operations only; optional model must select executable action names."""
    def __init__(self, model: TextModel | None = None):
        self.model = model

    def plan(self, week: str) -> list[PlanStep]:
        actions = list(ACTIONS)
        if self.model is not None:
            value = json_object(self.model.complete(
                '为运营周报规划执行步骤。只返回 JSON：{"actions":["fetch","compare","anomaly","report"]}。'
                '每个动作恰好一次，fetch 第一、report 最后，中间两步可交换。不要编造工具或数据。',
                f'生成 {week} 的周报计划。'))
            actions = value.get('actions')
            if (not isinstance(actions, list) or len(actions) != 4
                    or any(not isinstance(action, str) for action in actions)
                    or set(actions) != set(ACTIONS) or actions[0] != 'fetch' or actions[-1] != 'report'):
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'M3 Planner 返回了不可执行的动作序列', retryable=False)
        return [PlanStep(f's{i}', ACTIONS[action], action) for i, action in enumerate(actions, 1)]


class WeeklyReportExecutor:
    """Executes the supplied plan; never fills missing business facts with zero."""
    def __init__(self, fused_data: dict, previous_fused_data: dict | None = None, model: TextModel | None = None):
        self.data = deepcopy(fused_data)
        self.previous = deepcopy(previous_fused_data)
        self.model = model
        self.comparison = ''
        self.anomaly = ''
        self.report = ''

    def execute(self, steps: list[PlanStep]) -> str:
        for step in steps:
            start = time.perf_counter()
            step.status = 'running'
            try:
                step.result_summary = getattr(self, f'_step_{step.action}')()
                step.status = 'completed'
            except Exception:
                step.status = 'failed'
                raise
            finally:
                step.duration_ms = max(0, int((time.perf_counter() - start) * 1000))
        return self.report

    def _step_fetch(self):
        return f"已读取 {self.data['week']} 融合数据；订单 {self.data['order_count']}，销售额 {format_yuan(self.data['revenue_amount'])} 元"

    def _step_compare(self):
        if self.previous is None:
            self.comparison = '未提供上一周同口径原始指标，无法重新计算环比。'
        else:
            changes = []
            for key, label in [('revenue_amount', '销售额'), ('order_count', '订单量')]:
                change = _calc_change(self.data[key], self.previous[key])
                changes.append(f'{label}环比：' + (f'{change:+.2%}' if change is not None else '上周为零，变化率不适用'))
            pp = (self.data['conversion_rate'] - self.previous['conversion_rate']) * 100
            changes.append(f'转化率变化：{pp:+.2f} 个百分点')
            self.comparison = '；'.join(changes)
        return self.comparison

    def _step_anomaly(self):
        self.anomaly = f"输入数据记录：{self.data['anomaly']}。归因仅供核查，当前未接入额外归因证据。"
        return self.anomaly

    def _step_report(self):
        data = self.data
        mode = '模型规划与分析' if self.model else '本地标准计划与计算'
        self.report = (
            f"# {data['week']} 运营周报\n\n运行方式：{mode}；数据来自调用方提供的经营视图。\n\n"
            f"## 核心指标\n| 指标 | 数值 |\n|---|---:|\n"
            f"| 销售额 | {format_yuan(data['revenue_amount'])} 元 |\n"
            f"| 订单量 | {data['order_count']} |\n| 转化率 | {data['conversion_rate']:.2%} |\n\n"
            f"## 环比\n{self.comparison}\n\n## 异常与待核查项\n{self.anomaly}\n")
        if self.previous is not None:
            prior = self.previous
            self.report += (f"\n## 上周同口径依据（{prior['week']}）\n"
                f"销售额 {format_yuan(prior['revenue_amount'])} 元；订单量 {prior['order_count']}；"
                f"转化率 {prior['conversion_rate']:.2%}。\n{prior['anomaly']}\n")
        if self.model is not None:
            analysis = self.model.complete(
                '根据给定周报事实写简短运营建议。明确区分观测与假设，不补造缺失指标、外部数据或已执行动作。',
                self.report)
            if not isinstance(analysis, str) or not analysis.strip():
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'M3 分析结果为空', retryable=False)
            self.report += f'\n## 模型建议（待验证）\n{analysis.strip()}\n'
        return '已生成周报，保留数据缺口和统计口径说明'


class WeeklyReportAgent:
    manifest = MANIFEST

    def __init__(self, model: TextModel | None = None, *, mode: str | None = None):
        load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
        self.mode = mode or ('live' if model is not None else os.getenv('M3_MODE', 'local'))
        if self.mode not in ('local', 'live'):
            raise ValueError('M3_MODE must be local or live')
        self.model = model
        if self.mode == 'live' and self.model is None:
            config = text_config()
            self.model = ChatModel(config.base_url, config.api_key, config.model,
                                   float(os.getenv('LLM_TIMEOUT_SECONDS') or '120'))
        if self.mode == 'local' and self.model is not None:
            raise ValueError('local 模式不接受模型；注入模型时请使用 live')

    def invoke(self, request: AgentRequest) -> AgentResult:
        if request.capability_id != CAPABILITY_ID:
            return failure(request, ErrorCode.CONTRACT_MISMATCH, 'Request capability_id does not match M3')
        try:
            validate_data(request.payload, self.manifest.input_schema, ErrorCode.INVALID_INPUT)
            payload = deepcopy(request.payload)
            data, previous = payload['fused_data'], payload.get('previous_fused_data')
            try:
                validate_periods(payload)
            except ValueError as exc:
                raise ServiceError(ErrorCode.INVALID_INPUT, str(exc), retryable=False) from exc
            steps = WeeklyReportPlanner(self.model).plan(data['week'])
            report = WeeklyReportExecutor(data, previous, self.model).execute(steps)
            output = {'week': data['week'], 'report_markdown': report, 'steps': [s.to_dict() for s in steps]}
            validate_data(output, self.manifest.output_schema, ErrorCode.CONTRACT_MISMATCH)
            return result_for(request, status='completed', data=output)
        except (ServiceError, HubError) as exc:
            return failure(request, exc.code, str(exc), retryable=getattr(exc, 'retryable', False))
        except Exception as exc:
            return failure(request, ErrorCode.INTERNAL_ERROR, f'M3 执行失败：{type(exc).__name__}')


def invoke(request: AgentRequest) -> AgentResult:
    return WeeklyReportAgent().invoke(request)


def load_sample_view(week: str) -> dict:
    """Explicit standalone fixture adapter. Upstream gmv is a sample sales proxy."""
    week_start(week)
    from common.business_data import configured_data
    from common.weekly_data import load_business_view
    source = configured_data()
    if source is not None:
        return load_business_view(source, week)
    try:
        orders = strict_json_loads((FIXTURES / 'order_basic.json').read_text(encoding='utf-8'))['weeks'][week]
        behavior = strict_json_loads((FIXTURES / 'user_behavior.json').read_text(encoding='utf-8'))['weeks'][week]
    except ValueError as exc:
        raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'M3 数据源不是有效 JSON', retryable=False) from exc
    except KeyError as exc:
        raise ServiceError(ErrorCode.NOT_FOUND, f'M3 样例缺少 {week}', retryable=False) from exc
    anomalies = '；'.join(f"{a['date']} {a['metric']} {a['deviation']}：{a['reason']}" for a in orders.get('anomalies', []))
    return {'week': week, 'revenue_amount': orders['gmv_amount'], 'order_count': orders['order_count'],
            'conversion_rate': behavior['conversion_rate'], 'anomaly': anomalies or '样例未提供异常记录'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='M3 独立样例：本地 Plan/Execute 或真实模型规划')
    parser.add_argument('--week', default='2026-W41')
    parser.add_argument('--mode', choices=['local', 'live'], default=None)
    parser.add_argument('--manifest', action='store_true')
    args = parser.parse_args(argv)
    if args.manifest:
        print(MANIFEST.model_dump_json(indent=2))
        return 0
    try:
        payload = {'fused_data': load_sample_view(args.week)}
        try:
            payload['previous_fused_data'] = load_sample_view(_previous_week(args.week))
        except ServiceError as exc:
            if exc.code != ErrorCode.NOT_FOUND:
                raise
        agent = WeeklyReportAgent(mode=args.mode)
    except (OSError, ValueError, ServiceError) as exc:
        parser.error(str(exc))
    request = AgentRequest(request_id=f'req-{uuid4().hex[:12]}', task_id=f'task-{uuid4().hex[:12]}',
        trace_id=f'trace-{uuid4().hex[:16]}', capability_id=CAPABILITY_ID, payload=payload)
    result = agent.invoke(request)
    print(result.model_dump_json(indent=2))
    return 0 if result.status == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
