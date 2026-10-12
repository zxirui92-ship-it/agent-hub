from common.errors import ErrorCode
from typing import Any

from pydantic import ValidationError

from common.contracts import ExecutionPlan, ExecutionStep, LiteralBinding
from hub_platform.errors import HubError
from hub_platform.registry import CapabilityRegistry
from hub_platform.schema import compatible, field_schema, validate_data


class PlanValidator:
    def __init__(self, registry: CapabilityRegistry, max_steps: int = 32) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.registry = registry
        self.max_steps = max_steps

    def validate(self, raw: ExecutionPlan | dict[str, Any]) -> ExecutionPlan:
        try:
            plan = ExecutionPlan.model_validate(raw.model_dump() if isinstance(raw, ExecutionPlan) else raw)
        except ValidationError as exc:
            raise HubError(ErrorCode.INVALID_PLAN, str(exc)) from exc
        if len(plan.steps) > self.max_steps:
            raise HubError(ErrorCode.EXECUTION_LIMIT, f"Plan exceeds {self.max_steps} steps")
        steps = {step.step_id: step for step in plan.steps}
        if len(steps) != len(plan.steps):
            raise HubError(ErrorCode.DUPLICATE_STEP, "step_id must be unique")
        for step in plan.steps:
            try:
                self.registry.get_manifest(step.capability_id)
            except HubError as exc:
                raise HubError(exc.code, str(exc), step.step_id) from exc
            if len(set(step.depends_on)) != len(step.depends_on):
                raise HubError(ErrorCode.INVALID_DEPENDENCY, "Duplicate dependency", step.step_id)
            missing = set(step.depends_on) - steps.keys()
            if missing:
                raise HubError(ErrorCode.INVALID_DEPENDENCY, f"Missing dependencies: {sorted(missing)}", step.step_id)
        ordered = self.topological_steps(plan)
        ancestors: dict[str, set[str]] = {}
        for step in ordered:
            upstream = set(step.depends_on)
            for dep in step.depends_on:
                upstream.update(ancestors[dep])
            ancestors[step.step_id] = upstream
            manifest = self.registry.get_manifest(step.capability_id)
            properties = manifest.input_schema.get("properties", {})
            missing = set(manifest.input_schema.get("required", [])) - step.inputs.keys()
            extra = step.inputs.keys() - properties.keys()
            if missing or extra:
                raise HubError(ErrorCode.INVALID_INPUT, f"Missing inputs: {sorted(missing)}; undeclared inputs: {sorted(extra)}", step.step_id)
            for key, binding in step.inputs.items():
                target = properties[key]
                if isinstance(binding, LiteralBinding):
                    validate_data(binding.literal, target, ErrorCode.INVALID_INPUT, step.step_id)
                    continue
                source_id, _, *path = binding.ref.split(".")
                if source_id not in upstream:
                    raise HubError(ErrorCode.INVALID_REFERENCE, f"Reference must point to an upstream dependency: {binding.ref}", step.step_id)
                source_manifest = self.registry.get_manifest(steps[source_id].capability_id)
                source = field_schema(source_manifest.output_schema, path, step.step_id)
                if not compatible(source, target):
                    raise HubError(ErrorCode.CONTRACT_MISMATCH, f"Incompatible binding: {binding.ref} -> {key}", step.step_id)
        return plan

    @staticmethod
    def topological_steps(plan: ExecutionPlan) -> list[ExecutionStep]:
        """Stable Kahn ordering: original list order breaks ties between ready steps."""
        done: set[str] = set()
        remaining = list(plan.steps)
        ordered: list[ExecutionStep] = []
        while remaining:
            ready = [step for step in remaining if set(step.depends_on) <= done]
            if not ready:
                raise HubError(ErrorCode.CYCLIC_DEPENDENCY, "Plan dependency graph contains a cycle")
            for step in ready:
                ordered.append(step)
                done.add(step.step_id)
                remaining.remove(step)
        return ordered
