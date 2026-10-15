"""M5 business contract shared by the real module and deterministic mock.

Version 2.0 replaces the local draft's report input and roles object.
"""
from common.money import yuan_schema
from common.contracts import CapabilityManifest
from common.fusion_contract import fused_schema
from common.iso_week import week_schema


def promotion_manifest() -> CapabilityManifest:
    text = {"type": "string", "minLength": 1, "pattern": r"\S"}
    week = week_schema()
    money = yuan_schema()
    fused = fused_schema()
    return CapabilityManifest(
        capability_id="m5.promotion_plan", version="3.0", name="大促方案协同",
        description="根据大促目标及可选周报、融合数据和预算，由产品、运营、数据、客服四角色形成统一方案。",
        input_schema={
            "type": "object", "additionalProperties": False, "required": ["goal"],
            "properties": {"goal": text, "week": week, "budget_amount": money,
                           "report_markdown": text, "fused_data": fused},
        },
        output_schema={
            "type": "object", "additionalProperties": False,
            "required": ["plan_markdown", "roles"],
            "properties": {
                "plan_markdown": text,
                "roles": {"type": "array", "minItems": 4, "maxItems": 4, "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["role", "contribution", "rationale"],
                    "properties": {
                        "role": {"type": "string", "enum": ["product", "operation", "data", "service"]},
                        "contribution": text, "rationale": {"type": "string"},
                    },
                }},
            },
        },
        preconditions=["payload.goal 非空"], side_effects="read_only",
        execution_mode="immediate", supports_resume=False, owner="程炜",
    )
