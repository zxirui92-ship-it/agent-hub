from common.contracts import AgentModule, CapabilityManifest
from hub_platform.errors import HubError
from hub_platform.schema import check_schema


class CapabilityRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, tuple[CapabilityManifest, AgentModule]] = {}

    def register(self, manifest: CapabilityManifest, module: AgentModule) -> None:
        manifest = CapabilityManifest.model_validate(manifest.model_dump())
        if manifest.capability_id in self._entries:
            raise HubError("DUPLICATE_CAPABILITY", f"Already registered: {manifest.capability_id}")
        if not callable(getattr(module, "invoke", None)):
            raise HubError("CONTRACT_MISMATCH", "Module must expose invoke(request)")
        check_schema(manifest.input_schema)
        check_schema(manifest.output_schema)
        self._entries[manifest.capability_id] = (manifest.model_copy(deep=True), module)

    def get(self, capability_id: str) -> AgentModule:
        return self._entry(capability_id)[1]

    def get_manifest(self, capability_id: str) -> CapabilityManifest:
        return self._entry(capability_id)[0].model_copy(deep=True)

    def list_capabilities(self) -> list[CapabilityManifest]:
        return [manifest.model_copy(deep=True) for manifest, _ in self._entries.values()]

    def _entry(self, capability_id: str) -> tuple[CapabilityManifest, AgentModule]:
        if capability_id not in self._entries:
            raise HubError("UNKNOWN_CAPABILITY", f"Unknown capability: {capability_id}")
        return self._entries[capability_id]
