"""Regression tests for LLMEngine._extract_json / chat_json parsing.

The two "real" cases are trimmed copies of actual intent-model (Phi-3.5)
responses captured on 2026-10-25 for "Create a folder named ... on the
Desktop". The old brace-counter reduced both to step 1 only, which made the
harness task fail 0/5 as a false success.
"""
import json
from unittest import mock

import pytest

from Mei.cognition.llm.engine import LLMEngine

TWO_STEPS = """[
  {"step_id": 1, "description": "Navigate to the User Desktop directory", "domain": "file",
   "parameters": {"path": "C:/Users/Asus/Desktop"}},
  {"step_id": 2, "description": "Create a new folder named mei_harness_x", "domain": "file",
   "parameters": {"path": "C:/Users/Asus/Desktop/mei_harness_x"}}
]"""

REAL_FENCED = f"```json\n{TWO_STEPS}\n```"
REAL_TRAILING_PROSE = (
    f"{TWO_STEPS}\nNote: The expected_output for step 1 is a confirmation ...\n"
    "The complete JSON array with the implicit wait step included:\n[\n  {\n    \"step_id\": 1,"
)


def _engine() -> LLMEngine:
    return object.__new__(LLMEngine)  # _extract_json needs no model or config


def _extract(text):
    s = _engine()._extract_json(text)
    return None if s is None else json.loads(s)


@pytest.mark.parametrize("text", [REAL_FENCED, REAL_TRAILING_PROSE], ids=["fenced", "trailing-prose"])
def test_real_responses_keep_every_step(text):
    steps = _extract(text)
    assert isinstance(steps, list)
    assert [s["step_id"] for s in steps] == [1, 2]


def test_object_still_extracted():
    assert _extract('Sure! {"action": "wait", "parameters": {"seconds": 1}} done') == \
        {"action": "wait", "parameters": {"seconds": 1}}


def test_braces_inside_strings_do_not_break_parsing():
    assert _extract('```json\n{"description": "type } then {", "n": 1}\n```') == \
        {"description": "type } then {", "n": 1}


def test_leading_bracket_prose_is_skipped():
    assert _extract("[note] here it is: [1, 2]") == [1, 2]


def test_no_json_returns_none():
    assert _extract("I cannot help with that.") is None


def test_chat_json_returns_full_list_for_fenced_array():
    eng = _engine()
    eng._name, eng._temperature = "intent", 0.1
    with mock.patch.object(LLMEngine, "chat", return_value=REAL_FENCED):
        result = eng.chat_json([{"role": "user", "content": "x"}], system_prompt="json")
    assert isinstance(result, list) and len(result) == 2
