"""Router + Skill architecture: validate → select → dispatch → serialize.

The Router chooses internal plugins only; the platform owns cross-module plans.
"""
from datetime import datetime, timezone
import json
import logging
from common.config_env import secret_values

from agents.router.registry import SkillRegistry
from agents.router.routing import IntentRouter, RouteDecision
from common.contracts import AgentRequest, AgentResult, ErrorDetail
from common.errors import ErrorCode, ServiceError
from common.gateway_contract import gateway_manifest
from common.artifact_intent import image_requested
from hub_platform.errors import HubError
from hub_platform.schema import validate_data

LOGGER = logging.getLogger('agent_hub.m4')


def public_message(message: str) -> str:
    for value in secret_values():
        message = message.replace(value, '[redacted]')
    return message


class RouterAgent:
    manifest = gateway_manifest()

    def __init__(self, skills: SkillRegistry, router: IntentRouter):
        self.skills, self.router = skills, router

    def invoke(self, request: AgentRequest) -> AgentResult:
        correlation = {key: getattr(request, key) for key in ('request_id', 'task_id', 'trace_id', 'capability_id')}
        decision = None
        try:
            if request.capability_id != self.manifest.capability_id:
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Request capability_id does not match M4')
            validate_data(request.payload, self.manifest.input_schema, ErrorCode.INVALID_INPUT)
            query = request.payload['query']
            if not query.strip():
                raise ServiceError(ErrorCode.INVALID_INPUT, 'M4 requires a nonempty query string')
            kind = request.payload.get('output_kind')
            if kind is None and image_requested(query):
                kind = 'image'
            facts = request.payload.get('fused_data')
            if facts is not None and kind != 'image':
                raise ServiceError(ErrorCode.INVALID_INPUT, 'fused_data 必须配合 output_kind=image 使用')
            expected = {'image': 'image_gen', 'code': 'code_gen'}.get(kind)
            catalog = self.skills.list_skills()
            if expected:
                catalog = [skill for skill in catalog if skill.name == expected]
            decision = self.router.select(query, catalog)
            if not isinstance(decision, RouteDecision) or not isinstance(decision.route_reason, str) or not decision.route_reason.strip():
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Router returned an invalid decision')
            if decision.skill_name is None:
                raise ServiceError(ErrorCode.UNKNOWN_CAPABILITY, f'Unable to route: {decision.route_reason}')
            if not isinstance(decision.skill_name, str):
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Skill name must be a string')
            if expected and decision.skill_name != expected:
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH,
                    f'请求交付 {kind}，只能使用 {expected}，不能使用 {decision.skill_name}')
            self._log(request, 'running', decision)
            skill_payload = {'query': query}
            if facts is not None:
                skill_payload['fused_data'] = facts
            value = self.skills.invoke(decision.skill_name, skill_payload)
            if kind == 'image':
                try:
                    generated = json.loads(value)
                    images = generated['images']
                    if not isinstance(images, list) or not images or not all(
                        isinstance(item, dict) and any(isinstance(item.get(key), str) and item[key]
                            for key in ('image_url', 'b64_json', 'image_base64')) for item in images):
                        raise ValueError('Missing image resource')
                except (ValueError, KeyError, TypeError) as exc:
                    raise ServiceError(ErrorCode.CONTRACT_MISMATCH, '图片工具未返回图片资源，不能将文本或代码标为成图完成') from exc
                if facts is not None:
                    generated['verified_facts'] = facts
                    generated['warning'] = '图片为模型生成，请核对图中文字；统计范围仅限所示周次，非双十一全周期成果。'
                    value = json.dumps(generated, ensure_ascii=False)
            self._log(request, 'completed', decision)
            return AgentResult(**correlation, status='completed', data={
                'skill_name': decision.skill_name, 'result': value, 'route_reason': public_message(decision.route_reason)})
        except (ServiceError, HubError) as exc:
            stage = f'Skill {decision.skill_name}' if isinstance(decision, RouteDecision) else 'M4 意图路由'
            return self._failure(request, correlation, decision, exc.code, f'{stage}：{exc}', getattr(exc, 'retryable', False))
        except Exception as exc:
            # Only the injected router/Skill boundary: expose type + public message, no traceback.
            return self._failure(request, correlation, decision, ErrorCode.INTERNAL_ERROR,
                                 f'{type(exc).__name__}: {exc}', False)

    def _failure(self, request, correlation, decision, code, message, retryable):
        self._log(request, 'failed', decision, code)
        data = {}
        if isinstance(decision, RouteDecision) and isinstance(decision.skill_name, str):
            data = {'skill_name': decision.skill_name, 'result': '', 'route_reason': public_message(str(decision.route_reason))}
        return AgentResult(**correlation, status='failed', data=data, error=ErrorDetail(
            code=code, message=public_message(message), retryable=retryable,
            request_id=request.request_id, task_id=request.task_id, trace_id=request.trace_id))

    @staticmethod
    def _log(request, status, decision, code=None):
        event = {'ts': datetime.now(timezone.utc).isoformat(), 'level': 'error' if code else 'info',
                 'trace_id': request.trace_id, 'task_id': request.task_id, 'request_id': request.request_id,
                 'capability_id': request.capability_id, 'module': 'm4', 'status': status,
                 'tool_name': decision.skill_name if isinstance(decision, RouteDecision) else None,
                 'reason': public_message(str(decision.route_reason)) if isinstance(decision, RouteDecision) else None,
                 'output_kind': request.payload.get('output_kind'),
                 'data_week': (request.payload.get('fused_data') or {}).get('week') if isinstance(request.payload.get('fused_data'), dict) else None,
                 'error_code': code.value if code else None}
        LOGGER.log(logging.ERROR if code else logging.INFO, json.dumps(event, ensure_ascii=False))
