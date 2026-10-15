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
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from common.model_config import text_config

from hub_platform.conversation import Conversation
from hub_platform.errors import HubError
from hub_platform.planner import DynamicPlanner, configured_model
from hub_platform.demo_agents import create_mock_registry
from web.offline_planner import build_offline_planner

STATIC_DIR = Path(__file__).resolve().parent / "static"
ROOT_DIR = STATIC_DIR.parent.parent


def build_registry(real_flags: dict):
    """复刻 cli.py 的模块组装：默认七个 Mock，--real-m* 逐个替换为真实模块。"""
    registry = create_mock_registry()
    if not any(real_flags.values()):
        return registry
    from hub_platform.registry import CapabilityRegistry
    modules = {}
    try:
        if real_flags.get("m1"):
            from agents.single_agent import SingleAgent
            modules[SingleAgent().manifest.capability_id] = SingleAgent()
        if real_flags.get("m2"):
            from agents.react_agent import ReActAgent
            modules[ReActAgent().manifest.capability_id] = ReActAgent()
        if real_flags.get("m6"):
            from agents.blackboard import DataFusionModule
            m6 = DataFusionModule()
            modules[m6.manifest.capability_id] = m6
        if real_flags.get("m3"):
            from agents.plan_execute import WeeklyReportAgent
            m3 = WeeklyReportAgent()
            modules[m3.manifest.capability_id] = m3
        if real_flags.get("m7"):
            from agents.workflow.refund_graph import RefundWorkflow
            m7 = RefundWorkflow()
            modules[m7.manifest.capability_id] = m7
        if real_flags.get("m4"):
            from agents.router.factory import create_agent
            m4 = create_agent()
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
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            return {}

    def _session(self, session_id):
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
            return self._send_json({"mode": self.server.mode, "capabilities": caps})
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
        text = (body.get("text") or "").strip()
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
        decision = {
            "approved": bool(body.get("approved")),
            "reviewer": str(body.get("reviewer") or "").strip(),
            "material_complete": bool(body.get("material_complete")),
        }
        if not step_id or not decision["reviewer"]:
            return self._send_json({"error": {"code": "INVALID_INPUT",
                                             "message": "审批需要 step_id、reviewer（审核人）与 approved/material_complete"}}, 400)
        task_id = body.get("task_id") or None
        with sess["lock"]:
            turn = sess["conv"].review(step_id, decision, task_id=task_id)
            return self._send_json(turn.model_dump(mode="json"))

    # ---- 模块直调（绕过规划器，单步执行单个能力） ----
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
            payload = {}
        if not capability_id:
            return self._send_json({"error": {"code": "INVALID_INPUT", "message": "缺少 capability_id"}}, 400)
        plan = self._build_single_plan(capability_id, payload)
        task_id = f"task-{uuid4().hex[:12]}"
        trace_id = f"trace-{uuid4().hex[:16]}"
        with sess["lock"]:
            try:
                report = sess["conv"].executor.execute(
                    plan, task_id=task_id, trace_id=trace_id,
                    context={"session_id": sess["conv"]._context.session_id})
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
        decision = {
            "approved": bool(body.get("approved")),
            "reviewer": str(body.get("reviewer") or "").strip(),
            "material_complete": bool(body.get("material_complete")),
        }
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
            getattr(sess["conv"], method)()
            return self._send_json(sess["conv"].context.model_dump(mode="json"))

    # ---- 静态托管 ----
    def _serve_static(self, rel_path: Path, content_type):
        target = (STATIC_DIR / rel_path).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
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
        self.sessions = {}
        self._lock = threading.Lock()

    def new_session(self):
        from uuid import uuid4
        with self._lock:
            sid = f"sess-{uuid4().hex[:12]}"
            self.sessions[sid] = {
                "conv": Conversation(self.planner),
                "lock": threading.Lock(),
            }
            return sid


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent Hub 前端接入服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--offline", action="store_true",
                        help="强制使用离线演示 Planner（无需 LLM 配置）")
    for i in range(1, 8):
        parser.add_argument(f"--real-m{i}", action="store_true",
                            help=f"用真实 M{i} 模块替换 Mock")
    args = parser.parse_args(argv)

    real_flags = {f"m{i}": getattr(args, f"real_m{i}") for i in range(1, 8)}
    registry = build_registry(real_flags)

    offline = args.offline or not llm_configured()
    if offline:
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


if __name__ == "__main__":
    main()
