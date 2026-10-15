"""Exercise Web composition and real HTTP boundaries without model charges."""
import pytest
import json
import socket
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from web import server

_connect = socket.socket.connect


@pytest.fixture
def http_app(monkeypatch, request):
    real_refund = getattr(request, 'param', False)
    if real_refund:
        monkeypatch.setenv('HUB_DATA_DIR', 'data/group02')
    def local_only(sock, address):
        assert address[0] in ('127.0.0.1', '::1')
        return _connect(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', local_only)
    registry = server.build_registry({'m7':True}) if real_refund else server.create_mock_registry()
    app = server.HubServer(('127.0.0.1', 0), registry, server.build_offline_planner(registry), 'offline')
    thread = threading.Thread(target=app.serve_forever, daemon=True)
    thread.start()
    def request(path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = Request(f'http://127.0.0.1:{app.server_port}' + path, data=data,
                      headers={'Content-Type':'application/json'})
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())
    yield request
    app.shutdown()
    app.server_close()
    thread.join(timeout=3)


@pytest.mark.parametrize('raw', [b'[]', b'{broken', b'null'])
def test_http_invalid_json_returns_error_instead_of_disconnect(http_app, raw):
    code, value = http_app('/api/chat', raw=raw)
    assert code == 400 and value['error']['code'] == 'INVALID_INPUT'


@pytest.mark.parametrize('endpoint', ['/api/review', '/api/invoke/review'])
def test_http_review_rejects_string_false(http_app, endpoint):
    _, session = http_app('/api/session', {})
    code, value = http_app(endpoint, {**session, 'step_id':'s1', 'task_id':'task-000000000001',
                                    'approved':'false', 'material_complete':True, 'reviewer':'tester'})
    assert code == 400 and value['error']['code'] == 'INVALID_INPUT'


def test_live_examples_use_current_shared_order_and_budget(monkeypatch):
    monkeypatch.setenv('HUB_DATA_DIR', 'data/group02')
    examples = server.build_examples('real')
    assert examples['m7.refund_approval']['order_id'] == '2025100004'
    assert examples['m7.refund_approval']['refund_amount'] == 1099.0
    assert examples['m5.promotion_plan']['budget_amount'] == 10000.0
    assert examples['m3.weekly_report']['fused_data']['revenue_amount'] == 12680000.0


@pytest.mark.parametrize('http_app', [True], indirect=True)
@pytest.mark.parametrize('approved', [True, False])
def test_http_real_refund_wait_and_review(http_app, approved):
    _, session = http_app('/api/session', {})
    _, report = http_app('/api/invoke', {**session, 'capability_id':'m7.refund_approval',
        'payload':{'order_id':'2025100004', 'refund_amount':1099.0, 'reason':'买错了'}})
    assert report['status'] == 'waiting_approval'
    code, final = http_app('/api/invoke/review', {**session, 'task_id':report['task_id'],
        'step_id':'s1', 'approved':approved, 'reviewer':'测试审核员', 'material_complete':True})
    assert code == 200 and final['status'] == 'completed'
    assert final['steps']['s1']['result']['data']['approval_status'] == ('approved' if approved else 'rejected')
    assert final['task_id'] == report['task_id'] and final['trace_id'] == report['trace_id']


@pytest.mark.parametrize('http_app', [True], indirect=True)
def test_http_reset_rotates_session_and_drops_direct_wait(http_app):
    _, session = http_app('/api/session', {})
    _, report = http_app('/api/invoke', {**session, 'capability_id':'m7.refund_approval',
        'payload':{'order_id':'2025100004', 'refund_amount':1099.0, 'reason':'买错了'}})
    _, context = http_app('/api/reset', session)
    assert context['session_id'] != session['session_id']
    assert http_app('/api/context?session_id=' + session['session_id'])[0] == 404
    code, value = http_app('/api/invoke/review', {'session_id':context['session_id'],
        'task_id':report['task_id'], 'step_id':'s1', 'approved':True,
        'material_complete':True, 'reviewer':'tester'})
    assert code == 400 and value['error']['code'] == 'NOT_FOUND'


def test_http_unknown_review_returns_error_without_disconnect(http_app):
    _, session = http_app('/api/session', {})
    code, value = http_app('/api/review', {**session, 'step_id':'s1',
        'approved':True, 'material_complete':True, 'reviewer':'tester'})
    assert code == 400 and value['error']['code'] == 'NOT_FOUND'


class CapturedServer:
    instance = None

    def __init__(self, addr, registry, planner, mode):
        self.registry, self.planner, self.mode = registry, planner, mode
        CapturedServer.instance = self

    def serve_forever(self):
        pass

    def server_close(self):
        pass


def test_default_web_registers_all_real_modules_in_live_mode(monkeypatch):
    monkeypatch.setattr(server, 'HubServer', CapturedServer)
    monkeypatch.setenv('LLM_BASE_URL', 'https://example.test/v1')
    monkeypatch.setenv('LLM_API_KEY', 'offline-test-key')
    monkeypatch.setenv('LLM_MODEL', 'test-model')
    for name, mode in [('M1_MODE','mock'), ('M2_MODE','local'), ('M3_MODE','local'), ('M4_MODE','mock')]:
        monkeypatch.setenv(name, mode)
    server.main([])
    app = CapturedServer.instance
    assert app.mode == 'real'
    for manifest in app.registry.list_capabilities():
        module = app.registry.get(manifest.capability_id)
        assert not type(module).__module__.endswith('demo_agents')
        if manifest.capability_id in ('m1.faq_chat', 'm2.order_tracking', 'm3.weekly_report'):
            assert module.mode == 'live'


def test_missing_model_config_cannot_silently_start_offline(monkeypatch):
    monkeypatch.setattr(server, 'HubServer', CapturedServer)
    monkeypatch.setattr(server, 'llm_configured', lambda: False)
    with pytest.raises(SystemExit):
        server.main([])


def test_offline_mode_requires_explicit_choice(monkeypatch):
    monkeypatch.setattr(server, 'HubServer', CapturedServer)
    server.main(['--offline'])
    assert CapturedServer.instance.mode == 'offline'
    assert all(type(CapturedServer.instance.registry.get(m.capability_id)).__module__.endswith('demo_agents')
               for m in CapturedServer.instance.registry.list_capabilities())
