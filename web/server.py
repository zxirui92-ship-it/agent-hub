"""Agent Hub 薄 HTTP 服务：把 Conversation 暴露为 Web API 并托管静态界面。

运行：python -m web  （项目根目录）

设计要点（见 docs/frontend_handoff.md）：
- 每个前端会话保留一个 Conversation 实例，不在每条消息上重建，否则会丢失
  多轮记忆与等待审批状态。
- 同一会话的请求串行执行（per-session 锁），避免发送消息与审批同时改状态。
- 模型调用可能耗时较长（真实经营链约 100s），放到请求线程，前端显示加载态。
- 不重写 Planner / Executor / 七个 Agent；只做组装与映射，错误体与报告原样透传。
"""
import argparse
from dataclasses import replace
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from dotenv import load_dotenv

from common.model_config import text_config
from common.json_data import strict_json_loads
from common.errors import ServiceError

from hub_platform.conversation import Conversation
from hub_platform.errors import HubError
from hub_platform.planner import DynamicPlanner, configured_model
from hub_platform.planner import public_diagnostic
from hub_platform.demo_agents import create_mock_registry
from web.offline_planner import build_offline_planner

STATIC_DIR = Path(__file__).resolve().parent / "static"
ROOT_DIR = STATIC_DIR.parent.parent


def build_examples(mode):
    """Use the selected local facts, rather than old amounts hardcoded in JS."""
    from common.business_data import configured_data
    from common.order_data import order_fact
    from agents.plan_execute import load_sample_view
    data = configured_data() if mode == 'real' else None
    order_id = '2025100004' if data else '2025101234'
    amount = data.order(order_id)['order_amount'] if data else order_fact(order_id)['order_amount']
    week = '2025-W41' if data else '2026-W41'
    previous = '2025-W40' if data else '2026-W40'
    # Offline examples are explicitly illustrative; live views use shared data.
    weekly = ({'fused_data': load_sample_view(week), 'previous_fused_data': load_sample_view(previous)}
              if mode == 'real' else {'fused_data': {'week':week, 'revenue_amount':12684300.0,
                  'order_count':84562, 'conversion_rate':.0242, 'anomaly':'离线演示样例'}})
    return {
        'm1.faq_chat': {'question':'小家电保修几年？请说明不同条目差异。'},
        'm2.order_tracking': {'order_id':'2025100003' if data else order_id, 'query':'查询订单与物流'},
        'm3.weekly_report': weekly,
        'm4.capability_gateway': {'query':'联网搜索近期电商新闻，提供来源。'},
        'm5.promotion_plan': {'goal':'制定下周预算10000元的大促方案',
            'week':week[:4] + '-W42', 'budget_amount':10000.0},
        'm6.data_fusion': {'week':week},
        'm7.refund_approval': {'order_id':order_id, 'refund_amount':amount, 'reason':'买错了，申请整单退款'},
    }


def build_registry(real_flags: dict | None = None):
    """Web defaults to seven real modules; explicit offline mode passes all False."""
    if real_flags is None:
        real_flags = {f'm{i}': True for i in range(1, 8)}
    registry = create_mock_registry()
    if not any(real_flags.values()):
        return registry
    from hub_platform.registry import CapabilityRegistry
    modules = {}
    try:
        if real_flags.get("m1"):
            from agents.single_agent import SingleAgent
            m1 = SingleAgent(mode='live')
            modules[m1.manifest.capability_id] = m1
        if real_flags.get("m2"):
            from agents.react_agent import ReActAgent
            m2 = ReActAgent(mode='live')
            modules[m2.manifest.capability_id] = m2
        if real_flags.get("m6"):
            from agents.blackboard import DataFusionModule
            m6 = DataFusionModule()
            modules[m6.manifest.capability_id] = m6
        if real_flags.get("m3"):
            from agents.plan_execute import WeeklyReportAgent
            m3 = WeeklyReportAgent(mode='live')
            modules[m3.manifest.capability_id] = m3
        if real_flags.get("m7"):
            from agents.workflow.refund_graph import RefundWorkflow
            m7 = RefundWorkflow()
            modules[m7.manifest.capability_id] = m7
        if real_flags.get("m4"):
            from agents.router.factory import create_agent
            from agents.router.config import Settings
            m4 = create_agent(replace(Settings.from_env(), mode='live'))
            modules[m4.manifest.capability_id] = m4
        if real_flags.get("m5"):
            from agents.multi_agent import PromotionAgent
            m5 = PromotionAgent()
            modules[m5.manifest.capability_id] = m5
    except ValueError as exc:
        raise SystemExit(f"真实模块初始化失败：{exc}")
    replacement = CapabilityRegistry()
    for manifest in registry.list_capabilities():
        module = modules.get(manifest.capability_id) or registry.get(manifest.capability_id)
        replacement.register(module.manifest, module)
    return replacement


def llm_configured() -> bool:
    try:
        cfg = text_config()
    except ValueError:
        return False
    return bool(cfg.base_url and cfg.api_key and cfg.model)


class HubHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentHubWeb/0.1"

    # ---- 工具 ----
    def log_message(self, fmt, *args):  # 安静日志
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text, content_type, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > 2_000_000:
            raise ValueError('请求体长度无效')
        if not length:
            return {}
        raw = self.rfile.read(length)
        value = strict_json_loads(raw.decode('utf-8'))
        if not isinstance(value, dict):
            raise ValueError('请求体必须是 JSON 对象')
        return value

    def _session(self, session_id):
        if not isinstance(session_id, str):
            raise ValueError('session_id 必须是字符串')
        return self.server.sessions.get(session_id)

    # ---- 路由 ----
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            return self._serve_static(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            return self._serve_static(STATIC_DIR / path[len("/static/"):], None)
        if path == "/api/capabilities":
            caps = [m.model_dump(mode="json") for m in self.server.registry.list_capabilities()]
            return self._send_json({"mode": self.server.mode, "capabilities": caps,
                                    'examples': self.server.examples})
        if path == "/api/health":
            return self._send_json({"status": "ok", "mode": self.server.mode})
        if path.startswith("/api/context"):
            qs = parsed.query
            from urllib.parse import parse_qs
            sid = parse_qs(qs).get("session_id", [""])[0]
            sess = self._session(sid)
            if not sess:
                return self._send_json({"error": {"code": "NOT_FOUND", "message": "会话不存在"}}, 404)
            with sess["lock"]:
                return self._send_json(sess["conv"].context.model_dump(mode="json"))
        return self._send_json({"error": {"code": "NOT_FOUND", "message": "未知路径"}}, 404)

    def do_POST(self):
        try:
            return self._post()
        except (ValueError, TypeError) as exc:
            return self._send_json({'error': {'code':'INVALID_INPUT', 'message':public_diagnostic(str(exc))}}, 400)
        except (HubError, ServiceError) as exc:
            return self._send_json({'error': {'code':exc.code.value,
                'message':public_diagnostic(str(exc)), 'retryable':getattr(exc, 'retryable', False)}}, 400)
        except Exception as exc:
            return self._send_json({'error': {'code':'INTERNAL_ERROR',
                'message':f'请求处理失败：{type(exc).__name__}', 'retryable':False}}, 500)

    def _post(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        if path == "/api/session":
            sid = self.server.new_session()
            return self._send_json({"session_id": sid, "mode": self.server.mode})
        if path == "/api/chat":
            return self._turn(body, execute=True)
        if path == "/api/plan":
            return self._turn(body, execute=False)
        if path == "/api/review":
            return self._review(body)
        if path == "/api/invoke":
            return self._invoke_single(body)
        if path == "/api/invoke/review":
            return self._invoke_review(body)
        if path == "/api/new":
            return self._simple(body, "new_task")
        if path == "/api/reset":
            return self._simple(body, "reset")
        return self._send_json({"error": {"code": "NOT_FOUND", "message": "未知路径"}}, 404)

    # ---- 业务映射 ----
    def _turn(self, body, *, execute):
        sess = self._session(body.get("session_id", ""))
        if not sess:
            return self._send_json({"error": {"code": "NOT_FOUND", "message": "会话不存在"}}, 404)
        text = body.get('text', '')
        if not isinstance(text, str):
            raise ValueError('text 必须是字符串')
        text = text.strip()
        if not text:
            return self._send_json({"error": {"code": "INVALID_INPUT", "message": "请输入任务目标"}}, 400)
        with sess["lock"]:
            turn = sess["conv"].submit(text, execute=execute)
            return self._send_json(turn.model_dump(mode="json"))

    def _review(self, body):
        sess = self._session(body.get("session_id", ""))
        if not sess:
            return self._send_json({"error": {"code": "NOT_FOUND", "message": "会话不存在"}}, 404)
        step_id = body.get("step_id")
        decision = self._decision(body)
        if not step_id or not decision["reviewer"]:
            return self._send_json({"error": {"code": "INVALID_INPUT",
                                             "message": "审批需要 step_id、reviewer（审核人）与 approved/material_complete"}}, 400)
        task_id = body.get("task_id") or None
        with sess["lock"]:
            turn = sess["conv"].review(step_id, decision, task_id=task_id)
            return self._send_json(turn.model_dump(mode="json"))

    # ---- 模块直调（绕过规划器，单步执行单个能力） ----
    @staticmethod
    def _decision(body):
        if any(type(body.get(key)) is not bool for key in ('approved', 'material_complete')):
            raise ValueError('approved/material_complete 必须是 JSON 布尔值')
        if not isinstance(body.get('reviewer'), str) or not body['reviewer'].strip():
            raise ValueError('请填写审核人')
        return {key: body[key] for key in ('approved', 'material_complete', 'reviewer')}

    @staticmethod
    def _build_single_plan(capability_id: str, payload: dict) -> dict:
        inputs = {k: {"literal": v} for k, v in (payload or {}).items()}
        plan_id = f"plan-{secrets.randbelow(100_000_000):08d}-001"
        return {"plan_id": plan_id, "goal": f"direct:{capability_id}",
                "steps": [{"step_id": "s1", "capability_id": capability_id,
                           "depends_on": [], "inputs": inputs}]}

    def _invoke_single(self, body):
        sess = self._session(body.get("session_id", ""))
        if not sess:
            return self._send_json({"error": {"code": "NOT_FOUND", "message": "会话不存在"}}, 404)
        capability_id = body.get("capability_id")
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise ValueError('payload 必须是 JSON 对象')
        if not capability_id:
            return self._send_json({"error": {"code": "INVALID_INPUT", "message": "缺少 capability_id"}}, 400)
        plan = self._build_single_plan(capability_id, payload)
        task_id = f"task-{uuid4().hex[:12]}"
        trace_id = f"trace-{uuid4().hex[:16]}"
        with sess["lock"]:
            try:
                report = sess["conv"].executor.execute(
                    plan, task_id=task_id, trace_id=trace_id,
                    context={"session_id": sess["conv"].context.session_id})
            except HubError as exc:
                return self._send_json({"error": {"code": exc.code.name, "message": str(exc),
                                                 "task_id": task_id, "trace_id": trace_id}}, 400)
            # 非等待任务不占用审批续跑状态
            if report.status != "waiting_approval":
                sess["conv"].executor.discard(task_id)
        return self._send_json({"task_id": task_id, "trace_id": trace_id,
                                **report.model_dump(mode="json")})

    def _invoke_review(self, body):
        """对直调产生的等待审批步骤提交决定（直接走 Executor 续跑，不依赖会话历史）。"""
        sess = self._session(body.get("session_id", ""))
        if not sess:
            return self._send_json({"error": {"code": "NOT_FOUND", "message": "会话不存在"}}, 404)
        step_id = body.get("step_id")
        task_id = body.get("task_id")
        decision = self._decision(body)
        if not step_id or not task_id or not decision["reviewer"]:
            return self._send_json({"error": {"code": "INVALID_INPUT",
                                             "message": "直调审批需要 step_id、task_id、reviewer 与 approved/material_complete"}}, 400)
        with sess["lock"]:
            try:
                report = sess["conv"].executor.resume(task_id, step_id, decision)
            except HubError as exc:
                return self._send_json({"error": {"code": exc.code.name, "message": str(exc),
                                                 "task_id": task_id}}, 400)
        return self._send_json({"task_id": task_id, "trace_id": report.trace_id,
                                **report.model_dump(mode="json")})

    def _simple(self, body, method):
        sess = self._session(body.get("session_id", ""))
        if not sess:
            return self._send_json({"error": {"code": "NOT_FOUND", "message": "会话不存在"}}, 404)
        with sess["lock"]:
            if method == 'reset':
                # Also drop direct-invoke waits, absent from Conversation history.
                sess['conv'] = Conversation(self.server.planner)
                with self.server._lock:
                    self.server.sessions.pop(body['session_id'], None)
                    self.server.sessions[sess['conv'].context.session_id] = sess
            else:
                getattr(sess["conv"], method)()
            return self._send_json(sess["conv"].context.model_dump(mode="json"))

    # ---- 静态托管 ----
    def _serve_static(self, rel_path: Path, content_type):
        target = (STATIC_DIR / rel_path).resolve()
        if not target.is_relative_to(STATIC_DIR.resolve()) or not target.is_file():
            return self._send_text("Not Found", "text/plain; charset=utf-8", 404)
        if content_type is None:
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".ico": "image/x-icon",
            }.get(target.suffix, "application/octet-stream")
        try:
            data = target.read_bytes()
        except OSError:
            return self._send_text("Not Found", "text/plain; charset=utf-8", 404)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class HubServer(ThreadingHTTPServer):
    def __init__(self, addr, registry, planner, mode):
        super().__init__(addr, HubHTTPRequestHandler)
        self.registry = registry
        self.planner = planner
        self.mode = mode
        self.examples = build_examples(mode)
        self.sessions = {}
        self._lock = threading.Lock()

    def new_session(self):
        from uuid import uuid4
        with self._lock:
            conversation = Conversation(self.planner)
            sid = conversation.context.session_id
            self.sessions[sid] = {
                "conv": conversation,
                "lock": threading.Lock(),
            }
            return sid


def main(argv=None):
    load_dotenv(ROOT_DIR / '.env', override=False)
    parser = argparse.ArgumentParser(description="Agent Hub 前端接入服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--offline", action="store_true",
                        help="强制使用离线演示 Planner（无需 LLM 配置）")
    for i in range(1, 8):
        parser.add_argument(f"--real-m{i}", action="store_true",
                            help=f"兼容旧命令；默认已使用真实 M{i} 模块")
    args = parser.parse_args(argv)

    if args.offline and any(getattr(args, f'real_m{i}') for i in range(1, 8)):
        parser.error('--offline 不可与 --real-m* 同时使用')
    if not args.offline and not llm_configured():
        parser.error('真实模式缺少有效的文本模型配置；运行 python -m scripts.check_live_config 检查。离线演示请显式使用 --offline。')
    registry = build_registry({f'm{i}': False for i in range(1, 8)} if args.offline else None)
    if args.offline:
        planner = build_offline_planner(registry)
        mode = "offline"
    else:
        planner = DynamicPlanner(registry, configured_model())
        mode = "real"

    server = HubServer((args.host, args.port), registry, planner, mode)
    print(f"Agent Hub 前端已启动：http://{args.host}:{args.port}/  （模式：{mode}）")
    print("已注册接口：POST /api/session /api/chat /api/plan /api/review "
          "/api/invoke /api/invoke/review /api/new /api/reset；"
          "GET /api/capabilities /api/health /api/context")
    if mode == "offline":
        print("离线演示模式：使用确定性 Planner + 七个 Mock，无需 LLM 配置。")
        print("配置 LLM 后重新启动即可切换到真实语义规划。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
