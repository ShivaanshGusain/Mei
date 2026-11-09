"""JSON Schema for one constrained planner tool call.

Converts ToolSpec schemas (``{"param": {"type": "str", "required": True}}``) into
JSON Schema so the decoding grammar constrains each tool's arguments, not only
the tool name. Kept free of llama_cpp imports so it can be unit-tested anywhere.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Optional

NO_TOOL_ACTION = "no_tool"

GRAMMAR_MODES = ("per_tool", "name_only", "off")
DEFAULT_GRAMMAR_MODE = "per_tool"

_TYPE_MAP = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}

# Optional parameters whose default silently changes what the tool does.
# The grammar makes the model state them, so a forgotten key can't fall back
# to the default (e.g. omitting is_dir created an empty file, not a folder).
FORCE_EXPLICIT: Dict[str, tuple] = {
    "create_file_or_folder": ("is_dir",),
}


def grammar_mode() -> str:
    mode = os.environ.get("MEI_TOOL_GRAMMAR", DEFAULT_GRAMMAR_MODE).strip().lower()
    return mode if mode in GRAMMAR_MODES else DEFAULT_GRAMMAR_MODE


def _is_required(spec: Dict[str, Any]) -> bool:
    # Some handler schemas misspell the key; "requried" on type_text's text
    # would otherwise silently make a required argument optional.
    return bool(spec.get("required", spec.get("requried", False)))


def _param_schema(spec: Dict[str, Any]) -> Dict[str, Any]:
    t = str(spec.get("type", "str")).strip()
    if t in _TYPE_MAP:
        return {"type": _TYPE_MAP[t]}
    if t.lower().startswith("list"):
        inner = t[t.find("[") + 1:t.rfind("]")].strip() if "[" in t else "str"
        return {"type": "array", "items": {"type": _TYPE_MAP.get(inner, "string")}}
    return {"type": "string"}


def tool_parameters_schema(tool_name: str, schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not schema:
        return {"type": "object"}
    properties: Dict[str, Any] = {}
    required = []
    forced = FORCE_EXPLICIT.get(tool_name, ())
    for name, spec in schema.items():
        spec = spec if isinstance(spec, dict) else {}
        properties[name] = _param_schema(spec)
        if _is_required(spec) or name in forced:
            required.append(name)
    out: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        # Must stay False. llama-cpp-python 0.3.4 compiles True into a broken
        # grammar: extra values must be objects, and an optional property can
        # only appear if an extra key follows it with no comma, so every
        # optional argument becomes impossible to emit. Keys a handler reads
        # but its schema omits must be added to the ToolSpec schema instead.
        "additionalProperties": False,
    }
    if required:
        out["required"] = required
    return out


def _call_object(action_schema: Dict[str, Any], parameters_schema: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {"action": action_schema, "parameters": parameters_schema},
        "required": ["action", "parameters"],
    }


def _no_tool_branch() -> Dict[str, Any]:
    return _call_object(
        {"type": "string", "enum": [NO_TOOL_ACTION]},
        {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
    )


def build_tool_call_schema(
    tool_names: Iterable[str],
    tool_schemas: Optional[Dict[str, Dict[str, Any]]] = None,
    mode: str = DEFAULT_GRAMMAR_MODE,
    allow_no_tool: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Return the response_format schema for one tool call, or None for mode "off".

    per_tool  — each branch pins one tool name to that tool's own argument
                schema, plus a no_tool branch.
    name_only — the original behaviour: enum over names, free-form parameters.
                No no_tool option unless allow_no_tool is set (used when
                per_tool degrades, so the prompt and grammar stay consistent).
    """
    names = list(tool_names)
    if mode == "off":
        return None
    if allow_no_tool is None:
        allow_no_tool = mode == "per_tool"

    if mode == "name_only" or tool_schemas is None:
        enum = names + ([NO_TOOL_ACTION] if allow_no_tool else [])
        return _call_object({"type": "string", "enum": enum}, {"type": "object"})

    branches = [
        _call_object({"type": "string", "enum": [name]},
                     tool_parameters_schema(name, tool_schemas.get(name)))
        for name in names
    ]
    if allow_no_tool:
        branches.append(_no_tool_branch())
    return {"anyOf": branches}
