from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


JsonObject = dict[str, Any]
ToolHandler = Callable[[JsonObject], JsonObject]
FILE_HINT_KEYS = {"path", "file", "files", "filename", "objectKey", "relativePath"}


@dataclass(frozen=True)
class ToolExample:
    name: str
    input: JsonObject
    description: str


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str
    summary: str
    input_schema: JsonObject
    output_schema: JsonObject
    examples: list[ToolExample]
    handler: ToolHandler
    side_effects: list[str]
    requires: list[str]

    def metadata(self) -> JsonObject:
        return {
            "name": self.name,
            "category": self.category,
            "summary": self.summary,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "examples": [
                {
                    "name": example.name,
                    "description": example.description,
                    "input": example.input,
                }
                for example in self.examples
            ],
            "sideEffects": self.side_effects,
            "requires": self.requires,
        }


class ToolValidationError(ValueError):
    pass


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _matches_type(value: Any, expected: str | list[str]) -> bool:
    allowed = expected if isinstance(expected, list) else [expected]
    actual = _type_name(value)
    if actual in allowed:
        return True
    if actual == "integer" and "number" in allowed:
        return True
    return False


def validate_json(schema: JsonObject, payload: Any, *, path: str = "$") -> None:
    expected_type = schema.get("type")
    if expected_type and not _matches_type(payload, expected_type):
        raise ToolValidationError(f"{path} must be {expected_type}, got {_type_name(payload)}")

    if schema.get("type") == "object" or isinstance(payload, dict):
        if not isinstance(payload, dict):
            return
        required = schema.get("required", [])
        for key in required:
            if key not in payload:
                raise ToolValidationError(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(payload) - set(properties)
            if extra:
                raise ToolValidationError(f"{path} has unexpected keys: {sorted(extra)}")
        for key, value in payload.items():
            child_schema = properties.get(key)
            if child_schema:
                validate_json(child_schema, value, path=f"{path}.{key}")

    if schema.get("type") == "array" and isinstance(payload, list):
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(payload):
                validate_json(item_schema, item, path=f"{path}[{index}]")

    enum = schema.get("enum")
    if enum is not None and payload not in enum:
        raise ToolValidationError(f"{path} must be one of {enum}")


def tool_result(*, ok: bool, data: JsonObject | None = None, error: JsonObject | None = None) -> JsonObject:
    return {"ok": ok, "data": data or {}, "error": error}


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ToolValidationError):
        return "TOOL_VALIDATION_ERROR"
    if isinstance(exc, KeyError):
        return "TOOL_NOT_FOUND"
    if isinstance(exc, PermissionError):
        return "TOOL_PERMISSION_ERROR"
    if isinstance(exc, FileNotFoundError):
        return "TOOL_FILE_NOT_FOUND"
    return "TOOL_RUNTIME_ERROR"


def _collect_files(value: Any) -> list[str]:
    files: list[str] = []

    def visit(node: Any, parent_key: str | None = None) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                visit(child, key)
            return
        if isinstance(node, list):
            for item in node:
                visit(item, parent_key)
            return
        if isinstance(node, str) and parent_key in FILE_HINT_KEYS:
            files.append(node)

    visit(value)
    return list(dict.fromkeys(files))


def _tool_error_result(name: str, payload: JsonObject, exc: Exception) -> JsonObject:
    return tool_result(
        ok=False,
        error={
            "code": _error_code(exc),
            "message": str(exc),
            "type": exc.__class__.__name__,
            "tool": name,
            "request": {
                "tool": name,
                "input": payload,
            },
            "files": _collect_files(payload),
        },
    )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def list_metadata(self) -> list[JsonObject]:
        return [self._tools[name].metadata() for name in sorted(self._tools)]

    def call(self, name: str, payload: JsonObject) -> JsonObject:
        try:
            spec = self.get(name)
            validate_json(spec.input_schema, payload)
            result = spec.handler(payload)
            validate_json(spec.output_schema, result)
            return result
        except Exception as exc:
            return _tool_error_result(name, payload, exc)

    def run_examples(self) -> list[JsonObject]:
        results: list[JsonObject] = []
        for spec in self._tools.values():
            for example in spec.examples:
                output = self.call(spec.name, example.input)
                results.append(
                    {
                        "tool": spec.name,
                        "example": example.name,
                        "ok": output["ok"],
                        "error": output.get("error"),
                    }
                )
        return results
