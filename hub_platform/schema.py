"""Small, explicit JSON Schema profile; unsupported constructs fail at registration.

Static binding checks prove shape/type compatibility. Value constraints are checked
on literals and on resolved runtime data, not via a general schema theorem prover.
"""
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from hub_platform.errors import HubError

_ALLOWED = {
    "$schema", "title", "description", "type", "properties", "required",
    "additionalProperties", "items", "enum", "minimum", "maximum",
    "minLength", "maxLength", "minItems", "maxItems",
}
_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


def check_schema(schema: dict[str, Any], *, root: bool = True) -> None:
    if not isinstance(schema, dict):
        raise HubError("UNSUPPORTED_SCHEMA", "Schema nodes must be objects, not boolean schemas")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise HubError("INVALID_SCHEMA", exc.message) from exc
    unknown = set(schema) - _ALLOWED
    if unknown:
        raise HubError("UNSUPPORTED_SCHEMA", f"Unsupported keywords: {sorted(unknown)}")
    kind = schema.get("type")
    if not isinstance(kind, str) or kind not in _TYPES:
        raise HubError("UNSUPPORTED_SCHEMA", "Every schema node requires one explicit type")
    if root and kind != "object":
        raise HubError("INVALID_SCHEMA", "Payload and output roots must be objects")
    if kind == "object":
        if schema.get("additionalProperties") is not False:
            raise HubError("UNSUPPORTED_SCHEMA", "Objects require additionalProperties=false")
        properties = schema.get("properties", {})
        if not set(schema.get("required", [])) <= set(properties):
            raise HubError("INVALID_SCHEMA", "Required fields must be declared in properties")
        for child in properties.values():
            check_schema(child, root=False)
    if kind == "array":
        if not isinstance(schema.get("items"), dict):
            raise HubError("UNSUPPORTED_SCHEMA", "Arrays require an items schema")
        check_schema(schema["items"], root=False)


def validate_data(data: Any, schema: dict[str, Any], code: str, step_id: str | None = None) -> None:
    error = next(Draft202012Validator(schema).iter_errors(data), None)
    if error:
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise HubError(code, f"{path}: {error.message}", step_id)


def field_schema(schema: dict[str, Any], path: list[str], step_id: str) -> dict[str, Any]:
    node = schema
    for part in path:
        if node.get("type") != "object" or part not in node.get("properties", {}):
            raise HubError("INVALID_REFERENCE", f"Undeclared output field: {'.'.join(path)}", step_id)
        node = node["properties"][part]
    return node


def compatible(source: dict[str, Any], target: dict[str, Any]) -> bool:
    a, b = source["type"], target["type"]
    if a != b:
        return a == "integer" and b == "number"
    if b == "object":
        src, dst = source.get("properties", {}), target.get("properties", {})
        if not set(target.get("required", [])) <= set(source.get("required", [])):
            return False
        return set(src) <= set(dst) and all(compatible(value, dst[key]) for key, value in src.items())
    if b == "array":
        return compatible(source["items"], target["items"])
    return True
