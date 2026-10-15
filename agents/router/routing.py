"""Intent selection only: no Skill execution and no calls to other M modules."""
from dataclasses import asdict, dataclass
import json
from typing import Protocol

from agents.router.registry import SkillDescription
from common.errors import ErrorCode, ServiceError
from common.llm import TextModel
from agents.router.structured import request_object


@dataclass(frozen=True)
class RouteDecision:
    skill_name: str | None
    route_reason: str


class IntentRouter(Protocol):
    def select(self, query: str, skills: list[SkillDescription]) -> RouteDecision: ...


class LlmRouter:
    def __init__(self, model: TextModel):
        self.model = model

    def select(self, query: str, skills: list[SkillDescription]) -> RouteDecision:
        if not skills:
            return RouteDecision(None, 'No Skills registered')
        prompt = ('Select exactly one registered Skill using its description and the user intent. '
                  'If none fits, or multiple unrelated requests require different Skills, use null. '
                  'Return only JSON with exactly skill_name (string or null) and route_reason '
                  '(short public explanation, no hidden reasoning). Never invent a Skill. Catalog:\n'
                  + json.dumps([asdict(skill) for skill in skills], ensure_ascii=False))
        def validate(value):
            name, reason = value.get('skill_name'), value.get('route_reason')
            if set(value) != {'skill_name', 'route_reason'} or (name is not None and not isinstance(name, str)) or not isinstance(reason, str) or not reason.strip():
                raise ServiceError(ErrorCode.CONTRACT_MISMATCH,
                    'Expected exactly skill_name (registered string or null) and route_reason (nonempty string)')
            if name is not None and name not in {skill.name for skill in skills}:
                raise ServiceError(ErrorCode.UNKNOWN_CAPABILITY, f'LLM selected unregistered Skill: {name}')
        value = request_object(self.model, prompt, query, validate, stage='M4 意图路由')
        return RouteDecision(value['skill_name'], value['route_reason'])


class ExplicitMockRouter:
    """Offline demonstration only. 'skill_name: request' is not semantic routing."""
    def select(self, query: str, skills: list[SkillDescription]) -> RouteDecision:
        name, separator, _ = query.partition(':')
        name = name.strip()
        if separator and name in {skill.name for skill in skills}:
            return RouteDecision(name, 'Mock route: explicitly selected by skill_name prefix; no LLM used')
        return RouteDecision(None, 'Mock router requires a registered skill_name: request prefix')
