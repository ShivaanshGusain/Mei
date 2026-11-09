"""The planner prompt must carry what intent decomposition already resolved.

2026-11-09 smoke test: the create step's description was "Create a new folder
named mei_harness_<id>" (no "Desktop"), while step.parameters held the full
Desktop path. The prompt dropped the parameters and fell back to an example
under the first write root, and xLAM wrote the folder into C:\\Users\\Asus\\Projects.
"""
from Mei.action.context import ExecutionContext
from Mei.cognition.planning import prompt_builder
from Mei.core.task import IntentStep

DESKTOP_PATH = "C:/Users/Asus/Desktop/mei_harness_ab6a6de0"


def _create_step():
    return IntentStep(
        step_id=2,
        description="Create a new folder named mei_harness_ab6a6de0",
        expected_output="Folder mei_harness_ab6a6de0 is created on the Desktop",
        domain="file",
        target="mei_harness_ab6a6de0",
        parameters={"path": DESKTOP_PATH},
    )


def test_prompt_includes_step_target_and_parameters(monkeypatch):
    # Skip embedding-based retrieval (loads sentence-transformers).
    monkeypatch.setattr(prompt_builder, "_retrieve_tools",
                        lambda desc, domain, top_k=5: ["create_file_or_folder"])
    prompt, tools = prompt_builder.build_step_prompt(_create_step(), ExecutionContext())
    assert tools == ["create_file_or_folder"]
    assert "STEP TARGET: mei_harness_ab6a6de0" in prompt
    assert DESKTOP_PATH in prompt


def test_env_example_follows_parameters_not_first_write_root():
    env = prompt_builder._get_env_state(_create_step(), ExecutionContext())
    example = [line for line in env.splitlines() if "EXAMPLE:" in line]
    assert example, f"no EXAMPLE line in env state:\n{env}"
    assert "Desktop" in example[0], example[0]


def test_step_without_hints_has_no_hint_lines(monkeypatch):
    monkeypatch.setattr(prompt_builder, "_retrieve_tools",
                        lambda desc, domain, top_k=5: ["wait"])
    step = IntentStep(step_id=1, description="Wait a moment", expected_output="", domain="utility")
    prompt, _ = prompt_builder.build_step_prompt(step, ExecutionContext())
    assert "STEP TARGET" not in prompt and "STEP PARAMETERS" not in prompt
