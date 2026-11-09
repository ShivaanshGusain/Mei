"""Tests for the per-tool constrained-decoding schema (Mei/cognition/llm/tool_schema.py).

llama_cpp isn't needed: these check the JSON Schema itself, including with a
small validator that the schema accepts and rejects the calls it should. Whether
llama-cpp-python's grammar converter accepts this schema shape must still be
checked on a machine with llama_cpp installed (see the engine's fallback chain).
"""
import pytest

from Mei.cognition.llm.tool_schema import (
    NO_TOOL_ACTION, build_tool_call_schema, grammar_mode, tool_parameters_schema,
)

CREATE = {"path": {"type": "str", "required": True},
          "is_dir": {"type": "bool", "required": False, "default": False},
          "content": {"type": "str", "required": False, "default": ""}}
TYPE_TEXT = {"text": {"type": "str", "requried": True}, "interval": {"type": "float", "required": False}}
HOTKEY = {"keys": {"type": "List[str]", "required": True}}
SCHEMAS = {"create_file_or_folder": CREATE, "type_text": TYPE_TEXT, "hotkey": HOTKEY, "wait": {}}

_PY = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
       "object": dict, "array": list}


def accepts(schema, value) -> bool:
    """Minimal validator for the subset tool_schema.py emits."""
    if "anyOf" in schema:
        return any(accepts(s, value) for s in schema["anyOf"])
    t = schema.get("type")
    if t:
        if t == "integer" and isinstance(value, bool):
            return False
        if t == "number" and isinstance(value, bool):
            return False
        if not isinstance(value, _PY[t]):
            return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if t == "object":
        if any(k not in value for k in schema.get("required", [])):
            return False
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props and not accepts(props[k], v):
                return False
            if k not in props and schema.get("additionalProperties") is False:
                return False
    if t == "array" and "items" in schema:
        return all(accepts(schema["items"], v) for v in value)
    return True


def test_per_tool_requires_is_dir_for_create():
    schema = build_tool_call_schema(["create_file_or_folder", "wait"], SCHEMAS, mode="per_tool")
    folder = {"action": "create_file_or_folder", "parameters": {"path": "C:/x", "is_dir": True}}
    missing = {"action": "create_file_or_folder", "parameters": {"path": "C:/x"}}
    wrong_type = {"action": "create_file_or_folder", "parameters": {"path": "C:/x", "is_dir": "yes"}}
    assert accepts(schema, folder)
    assert not accepts(schema, missing), "a folder call without is_dir must be rejected"
    assert not accepts(schema, wrong_type)


def test_per_tool_rejects_off_menu_and_accepts_no_tool():
    schema = build_tool_call_schema(["create_file_or_folder"], SCHEMAS, mode="per_tool")
    assert not accepts(schema, {"action": "delete_path", "parameters": {"path": "C:/x"}})
    assert accepts(schema, {"action": NO_TOOL_ACTION, "parameters": {"reason": "nothing fits"}})
    assert not accepts(schema, {"action": NO_TOOL_ACTION, "parameters": {}})


def test_tool_without_schema_keeps_free_parameters():
    assert tool_parameters_schema("wait", {}) == {"type": "object"}
    assert tool_parameters_schema("wait", None) == {"type": "object"}


def test_misspelled_requried_still_counts_as_required():
    params = tool_parameters_schema("type_text", TYPE_TEXT)
    assert params["required"] == ["text"]
    assert params["properties"]["interval"] == {"type": "number"}


def test_list_type_becomes_string_array():
    params = tool_parameters_schema("hotkey", HOTKEY)
    assert params["properties"]["keys"] == {"type": "array", "items": {"type": "string"}}


def test_name_only_is_the_original_schema_without_no_tool():
    schema = build_tool_call_schema(["a", "b"], SCHEMAS, mode="name_only")
    assert schema == {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["a", "b"]}, "parameters": {"type": "object"}},
        "required": ["action", "parameters"],
    }


def test_name_only_fallback_from_per_tool_keeps_no_tool():
    schema = build_tool_call_schema(["a"], SCHEMAS, mode="name_only", allow_no_tool=True)
    assert schema["properties"]["action"]["enum"] == ["a", NO_TOOL_ACTION]


def test_off_mode_has_no_schema():
    assert build_tool_call_schema(["a"], SCHEMAS, mode="off") is None


@pytest.mark.parametrize("env,expected", [
    (None, "per_tool"), ("name_only", "name_only"), (" OFF ", "off"), ("garbage", "per_tool"),
])
def test_grammar_mode_from_env(monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv("MEI_TOOL_GRAMMAR", raising=False)
    else:
        monkeypatch.setenv("MEI_TOOL_GRAMMAR", env)
    assert grammar_mode() == expected
