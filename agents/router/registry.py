"""A registry for internal Skills, independent of the platform capability registry."""
from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Protocol

from common.errors import ErrorCode, ServiceError


class Skill(Protocol):
    def run(self, payload: dict) -> str: ...


@dataclass(frozen=True)
class SkillDescription:
    name: str
    description: str


class SkillRegistry:
    def __init__(self):
        self._entries: dict[str, tuple[SkillDescription, Skill]] = {}

    def register(self, name: str, description: str, skill: Skill) -> None:
        if not re.fullmatch(r'[a-z][a-z0-9_]{2,39}', name) or not description.strip():
            raise ValueError('Skill name and description are required')
        if name in self._entries:
            raise ServiceError(ErrorCode.DUPLICATE_CAPABILITY, f'Skill already registered: {name}')
        if not callable(getattr(skill, 'run', None)):
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Skill must expose run(payload) -> str')
        self._entries[name] = (SkillDescription(name, description), skill)

    def get(self, name: str) -> Skill:
        if name not in self._entries:
            raise ServiceError(ErrorCode.UNKNOWN_CAPABILITY, f'Unknown Skill: {name}')
        return self._entries[name][1]

    def describe(self, name: str) -> SkillDescription:
        self.get(name)
        return self._entries[name][0]

    def list_skills(self) -> list[SkillDescription]:
        return [entry[0] for entry in self._entries.values()]

    def invoke(self, name: str, payload: dict) -> str:
        value = self.get(name).run(deepcopy(payload))
        if not isinstance(value, str) or not value.strip():
            raise ServiceError(ErrorCode.CONTRACT_MISMATCH, 'Skill.run must return nonempty text')
        return value
