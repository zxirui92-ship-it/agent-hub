from common.errors import ErrorCode
"""Mock demo composition root. Core registry/validator/executor never import mocks."""
import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

from common.contracts import ExecutionReport
from hub_platform.errors import HubError
from hub_platform.executor import Executor


def summary(value: object, limit: int = 400) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…（完整数据见 --json）"


def render_report(report: ExecutionReport) -> str:
    lines = [f"计划 ID: {report.plan_id}", f"任务 ID: {report.task_id}",
             f"Trace ID: {report.trace_id}", f"计划状态: {report.status}"]
    for step in report.steps.values():
        lines.extend([f"\n[{step.step_id}] {step.capability_id}",
                      f"  依赖: {', '.join(step.depends_on) or '无'} | 状态: {step.status.value}",
                      f"  输入: {summary(step.inputs)}"])
        if step.result:
            lines.append(f"  输出: {summary(step.result.data)}")
        if step.reason:
            lines.append(f"  原因: {step.reason}")
        if step.error:
            lines.append(f"  错误码: {step.error.code}")
    lines.append("\n执行轨迹:")
    for event in report.events:
        lines.append(f"  {event.sequence}. {event.step_id}: {event.status.value} — {event.reason}")
    lines.append(f"\n最终结果（已完成叶子步骤）: {summary(report.final_results, 2000)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Hub 第一阶段 Mock 执行器（不支持恢复）")
    parser.add_argument("plan", type=Path, nargs="?", help="ExecutionPlan JSON 文件")
    parser.add_argument("--max-steps", type=int, default=32)
    parser.add_argument("--json", action="store_true", help="完整结构化报告")
    parser.add_argument("--list-capabilities", action="store_true")
    args = parser.parse_args(argv)
    if args.max_steps < 1:
        parser.error("--max-steps 必须为正整数")
    if not args.plan and not args.list_capabilities:
        parser.error("需要计划文件或 --list-capabilities")
    # Test fixtures are intentionally not production package dependencies.
    from tests.mocks.agents import create_mock_registry

    registry = create_mock_registry()
    if args.list_capabilities:
        print(json.dumps([m.model_dump() for m in registry.list_capabilities()], ensure_ascii=False, indent=2))
        return 0
    task_id, trace_id = f"task-{uuid4().hex[:12]}", f"trace-{uuid4().hex[:16]}"
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
        report = Executor(registry, args.max_steps).execute(plan, task_id=task_id, trace_id=trace_id)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        error = HubError(ErrorCode.INVALID_PLAN_FILE, str(exc)).detail(trace_id, task_id)
        print(error.model_dump_json(indent=2))
        return 2
    except HubError as exc:
        print(exc.detail(trace_id, task_id).model_dump_json(indent=2))
        return 2
    print(report.model_dump_json(indent=2) if args.json else render_report(report))
    return {"completed": 0, "failed": 1, "waiting_approval": 3}[report.status]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
