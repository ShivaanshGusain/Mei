"""Check the GBNF that llama-cpp-python actually generates from tool_schema.py.

test_tool_schema.py validates the JSON Schema. This file goes one step further:
it runs llama-cpp-python's own schema-to-GBNF converter, compiles the resulting
grammar to a regex (inlining rules, recursion cut at a small depth), and checks
which tool-call strings the grammar admits. It caught a real bug: in 0.3.4,
"additionalProperties": true compiles to a grammar where an optional argument
can never be emitted on its own.

Skipped where llama_cpp isn't installed (it is in the Windows .venv).
"""
import json
import re

import pytest

lg = pytest.importorskip("llama_cpp.llama_grammar")

from Mei.cognition.llm.tool_schema import build_tool_call_schema  # noqa: E402

_TOK = re.compile(r'\s*("(?:\\.|[^"\\])*"|\[(?:\\.|[^\]\\])*\]|[A-Za-z0-9_-]+|[()|?*+])')


def _gbnf(schema):
    conv = lg.SchemaConverter(prop_order={}, allow_fetch=False, dotall=False, raw_pattern=False)
    conv.visit(schema, "")
    return conv.format_grammar()


def _rules(text):
    return {name.strip(): body.strip()
            for name, body in (line.split("::=", 1) for line in text.splitlines() if "::=" in line)}


def _tokens(body):
    out, pos = [], 0
    while pos < len(body) and body[pos:].strip():
        m = _TOK.match(body, pos)
        assert m, f"unexpected GBNF syntax near {body[pos:pos + 30]!r}"
        out.append(m.group(1))
        pos = m.end()
    return out


def _compile(name, rules, depth, budget=3):
    if depth.get(name, 0) >= budget:
        return "(?!)"
    depth[name] = depth.get(name, 0) + 1
    toks, i = _tokens(rules[name]), 0

    def alt():
        nonlocal i
        options = [seq()]
        while i < len(toks) and toks[i] == "|":
            i += 1
            options.append(seq())
        return "(?:" + "|".join(options) + ")"

    def seq():
        nonlocal i
        parts = []
        while i < len(toks) and toks[i] not in ("|", ")"):
            t = toks[i]
            i += 1
            if t == "(":
                atom = alt()
                i += 1  # closing paren
            elif t.startswith('"'):
                atom = "(?:" + re.escape(bytes(t[1:-1], "utf-8").decode("unicode_escape")) + ")"
            elif t.startswith("["):
                atom = t
            else:
                atom = "(?:" + _compile(t, rules, depth, budget) + ")"
            while i < len(toks) and toks[i] in "?*+":
                atom += toks[i]
                i += 1
            parts.append(atom)
        return "".join(parts)

    out = alt()
    depth[name] -= 1
    return out


def admits(schema, obj) -> bool:
    rx = re.compile(_compile("root", _rules(_gbnf(schema)), {}), re.S)
    return any(rx.fullmatch(json.dumps(obj, separators=sep)) for sep in ((", ", ": "), (",", ":")))


SCHEMAS = {
    "create_file_or_folder": {"path": {"type": "str", "required": True},
                              "is_dir": {"type": "bool", "required": False},
                              "content": {"type": "str", "required": False}},
    "focus_window": {"query": {"type": "str", "required": False},
                     "title": {"type": "str", "required": False},
                     "hwnd": {"type": "int", "required": False}},
    "hotkey": {"keys": {"type": "List[str]", "required": True},
               "hold_time": {"type": "float", "required": False}},
    "wait": {},
}
GRAMMAR = build_tool_call_schema(list(SCHEMAS), SCHEMAS, mode="per_tool")


def call(action, **params):
    return {"action": action, "parameters": params}


def test_grammar_converts():
    assert "root ::=" in _gbnf(GRAMMAR)


def test_folder_needs_is_dir():
    assert admits(GRAMMAR, call("create_file_or_folder", path="C:/x", is_dir=True))
    assert not admits(GRAMMAR, call("create_file_or_folder", path="C:/x"))


def test_optional_argument_alone_is_admitted():
    # The 0.3.4 additionalProperties:true regression: these were all rejected.
    assert admits(GRAMMAR, call("create_file_or_folder", path="C:/x", is_dir=False, content="hi"))
    assert admits(GRAMMAR, call("focus_window", query="Notepad"))
    assert admits(GRAMMAR, call("focus_window"))
    assert admits(GRAMMAR, call("hotkey", keys=["ctrl", "c"], hold_time=0.5))


def test_extra_keys_and_off_menu_rejected():
    assert not admits(GRAMMAR, call("focus_window", query="Notepad", zzz="x"))
    assert not admits(GRAMMAR, call("launch_app", app_name="notepad"))


def test_no_tool_branch():
    assert admits(GRAMMAR, call("no_tool", reason="nothing fits"))
    assert not admits(GRAMMAR, call("no_tool"))
