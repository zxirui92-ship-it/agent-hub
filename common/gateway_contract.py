"""M4's public business schema, shared by the mock and real implementation."""
from common.contracts import CapabilityManifest
from common.fusion_contract import fused_schema


def gateway_manifest() -> CapabilityManifest:
    string = {"type": "string", "minLength": 1}
    return CapabilityManifest(
        capability_id="m4.capability_gateway", version="1.1", name="能力网关",
        description="按请求选择已注册的搜索、知识库问答、代码或图片生成 Skill。海报成图使用 output_kind=image；经营数据须显式传入 fused_data，本模块无法读取会话历史。",
        input_schema={"type": "object", "properties": {"query": string,
                      "output_kind": {"type": "string", "enum": ["image", "code"]},
                      "fused_data": fused_schema()},
                      "required": ["query"], "additionalProperties": False},
        output_schema={"type": "object", "properties": {
            "skill_name": string, "result": string, "route_reason": string},
            "required": ["skill_name", "result", "route_reason"], "additionalProperties": False},
        preconditions=["query"], side_effects="read_only", execution_mode="immediate",
        supports_resume=False, owner="张熙睿",
    )
