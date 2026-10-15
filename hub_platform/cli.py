"""Demo composition root. Core registry/validator/executor never import mocks."""
from common.errors import ErrorCode
from common.json_data import strict_json_loads
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
    parser = argparse.ArgumentParser(description="Agent Hub：自然语言规划、会话或 JSON 计划执行")
    parser.add_argument("plan", type=Path, nargs="?", help="ExecutionPlan JSON 文件")
    parser.add_argument("--goal", help="自然语言任务；使用已配置的 LLM 生成计划")
    parser.add_argument("--chat", action="store_true", help="内存多轮会话，支持补充参数")
    parser.add_argument("--plan-only", action="store_true", help="只生成并校验计划，不调用业务模块")
    parser.add_argument("--max-steps", type=int, default=32)
    parser.add_argument("--json", action="store_true", help="完整结构化报告")
    parser.add_argument("--list-capabilities", action="store_true")
    parser.add_argument("--real-m4", action="store_true", help="Replace Mock M4 with RouterAgent; configuration via environment")
    parser.add_argument("--real-m3", action="store_true", help="Replace Mock M3 with Plan/Execute; M3_MODE=local (default) or live")
    parser.add_argument("--real-m7", action="store_true", help="Replace Mock M7 with the local LangGraph workflow")
    parser.add_argument("--real-m5", action="store_true", help="Replace Mock M5 with PromotionAgent; configured LLM required")
    parser.add_argument("--real-m1", action="store_true", help="Use SingleAgent; M1_MODE=live (default) or mock")
    parser.add_argument("--real-m2", action="store_true", help="Use ReActAgent; M2_MODE=live (default) or local; fixture order data")
    parser.add_argument("--real-m6", action="store_true", help="Use private Blackboard with weekly sample data")
    args = parser.parse_args(argv)
    if args.max_steps < 1:
        parser.error("--max-steps 必须为正整数")
    if sum((args.plan is not None, args.goal is not None, args.chat, args.list_capabilities)) != 1:
        parser.error("请选择计划文件、--goal、--chat 或 --list-capabilities 中的一项")
    if args.plan_only and not (args.goal is not None or args.chat):
        parser.error("--plan-only 需要 --goal 或 --chat")
    # Demo adapters are runtime resources, independent of the test package.
    from hub_platform.demo_agents import create_mock_registry

    registry = create_mock_registry()
    if any((args.real_m1, args.real_m2, args.real_m3, args.real_m4, args.real_m5, args.real_m6, args.real_m7)):
        from hub_platform.registry import CapabilityRegistry
        modules = {}
        if args.real_m1:
            from agents.single_agent import SingleAgent
            try:
                m1 = SingleAgent()
            except ValueError as exc:
                parser.error(str(exc))
            modules[m1.manifest.capability_id] = m1
        if args.real_m2:
            from agents.react_agent import ReActAgent
            try:
                m2 = ReActAgent()
            except ValueError as exc:
                parser.error(str(exc))
            modules[m2.manifest.capability_id] = m2
        if args.real_m6:
            from agents.blackboard import DataFusionModule
            m6 = DataFusionModule()
            modules[m6.manifest.capability_id] = m6
        if args.real_m3:
            from agents.plan_execute import WeeklyReportAgent
            try:
                m3 = WeeklyReportAgent()
            except ValueError as exc:
                parser.error(str(exc))
            modules[m3.manifest.capability_id] = m3
        if args.real_m7:
            from agents.workflow.refund_graph import RefundWorkflow
            m7 = RefundWorkflow()
            modules[m7.manifest.capability_id] = m7
        if args.real_m4:
            from agents.router.factory import create_agent
            try:
                m4 = create_agent()
            except ValueError as exc:
                parser.error(str(exc))
            modules[m4.manifest.capability_id] = m4
        if args.real_m5:
            from agents.multi_agent import PromotionAgent
            m5 = PromotionAgent()
            modules[m5.manifest.capability_id] = m5
        replacement = CapabilityRegistry()
        for manifest in registry.list_capabilities():
            module = modules.get(manifest.capability_id) or registry.get(manifest.capability_id)
            replacement.register(module.manifest, module)
        registry = replacement
    if args.list_capabilities:
        print(json.dumps([m.model_dump() for m in registry.list_capabilities()], ensure_ascii=False, indent=2))
        return 0
    if args.goal is not None or args.chat:
        from hub_platform.conversation import Conversation
        from hub_platform.planner import DynamicPlanner, configured_model
        try:
            session = Conversation(DynamicPlanner(registry, configured_model(), max_steps=args.max_steps))
        except ValueError as exc:
            parser.error(str(exc))
        if args.chat:
            return chat_loop(session, as_json=args.json, execute=not args.plan_only)
        turn = session.submit(args.goal, execute=not args.plan_only)
        print(turn.model_dump_json(indent=2) if args.json else render_turn(turn))
        return turn_exit_code(turn.status)
    task_id, trace_id = f"task-{uuid4().hex[:12]}", f"trace-{uuid4().hex[:16]}"
    try:
        plan = strict_json_loads(args.plan.read_text(encoding="utf-8-sig"))
        report = Executor(registry, args.max_steps).execute(plan, task_id=task_id, trace_id=trace_id)
    except (OSError, UnicodeError, ValueError) as exc:
        error = HubError(ErrorCode.INVALID_PLAN_FILE, str(exc)).detail(trace_id, task_id)
        print(error.model_dump_json(indent=2))
        return 2
    except HubError as exc:
        print(exc.detail(trace_id, task_id).model_dump_json(indent=2))
        return 2
    print(report.model_dump_json(indent=2) if args.json else render_report(report))
    return {"completed": 0, "failed": 1, "waiting_approval": 3}[report.status]


def turn_exit_code(status: str) -> int:
    return {'ready': 0, 'completed': 0, 'failed': 1, 'unsupported': 2,
            'waiting_approval': 3, 'needs_clarification': 4}[status]


def render_turn(turn) -> str:
    lines = [f"会话: {turn.session_id}", f"状态: {turn.status}", turn.message]
    if turn.plan:
        lines.extend(['\n生成的计划:', turn.plan.model_dump_json(indent=2)])
    if turn.report:
        lines.extend(['\n实际执行:', render_report(turn.report)])
    if turn.error:
        lines.append(f"错误码: {turn.error.code.value}")
    if len(turn.planning_attempts) > 1:
        lines.append(f"规划调用次数: {len(turn.planning_attempts)}（含非法计划修正）")
    return '\n'.join(lines)


def chat_loop(session, *, as_json=False, execute=True) -> int:
    print('输入任务或补充回答。/review JSON 提交审批；/new 新任务；/reset 清空会话；/context 查看上下文；/exit 退出。', file=sys.stderr)
    while True:
        try:
            print('你 > ', end='', file=sys.stderr, flush=True)
            text = input().strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if text == '/exit':
            return 0
        if not text:
            continue
        if text == '/new':
            session.new_task()
            print('已结束当前任务，上下文历史保留。', file=sys.stderr)
            continue
        if text == '/reset':
            session.reset()
            print('已清空会话。', file=sys.stderr)
            continue
        if text == '/context':
            print(session.context.model_dump_json(indent=None if as_json else 2))
            continue
        if text == '/review' or text.startswith('/review '):
            try:
                if not execute:
                    raise ValueError('预览模式不能提交审批')
                value = json.loads(text[len('/review'):].strip())
                if not isinstance(value, dict):
                    raise ValueError('审批参数须为 JSON 对象')
                step_id = value.pop('step_id')
                task_id = value.pop('task_id', None)
                if not isinstance(step_id, str) or (task_id is not None and not isinstance(task_id, str)):
                    raise ValueError('step_id/task_id 必须为字符串')
                turn = session.review(step_id, value, task_id=task_id)
                print(turn.model_dump_json() if as_json else render_turn(turn))
            except (ValueError, KeyError, HubError) as exc:
                print(json.dumps({'status':'failed', 'error':{'code':getattr(exc, 'code', ErrorCode.INVALID_INPUT).value,
                    'message':'审批命令无效；需要 step_id、approved、reviewer、material_complete，且须有待审核任务。'}}, ensure_ascii=False))
            continue
        turn = session.submit(text, execute=execute)
        print(turn.model_dump_json() if as_json else render_turn(turn))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
