"""
Stability scorer for episodic memory.

Computes a stability score [0.0 – 1.0] for an episode at write time.
The score reflects how safely the stored action sequence can be replayed
blindly without re-planning.

High stability (≥ 0.75): sequence uses deterministic tools with concrete
    parameters that are unlikely to change between runs.
    Example: create_file_or_folder(path="C:/Users/Asus/Desktop/test.py")

Medium stability (0.50 – 0.74): some steps have stable params, others may
    vary. Example: web_navigate to a fixed URL, but web_type with dynamic text.

Low stability (< 0.50): sequence relies on dynamic/contextual values,
    interactive elements, or relative paths that may not exist next run.
    Example: click(query="Search results item 3")

Stored on the Goal node as stability_score DOUBLE.
"""

import re
import json
from typing import List, Dict, Any

# ─────────────────────────────────────────────────────────────────────────────
# Base stability score per tool name
# ─────────────────────────────────────────────────────────────────────────────
TOOL_STABILITY: Dict[str, float] = {
    # Filesystem — deterministic, path-based
    "create_file_or_folder": 0.9,
    "list_files":            0.9,
    "get_cwd":               0.9,
    "get_system_info":       0.9,
    "change_directory":      0.9,
    "delete_path":           0.9,
    "rename_or_move":        0.9,

    # App / window / navigation — deterministic targets
    "launch_app":            0.8,
    "terminate_app":         0.8,
    "focus_window":          0.8,
    "find_window":           0.8,
    "verify_window":         0.8,
    "minimize_window":       0.8,
    "maximize_window":       0.8,
    "restore_window":        0.8,
    "close_window":          0.8,
    "web_navigate":          0.8,
    "hotkey":                0.8,
    "wait":                  0.8,
    "download_file":         0.8,

    # File content + shell — result depends on file/system state
    "write_to_file":         0.6,
    "read_file":             0.6,
    "edit_file_by_lines":    0.6,
    "run_shell_command":     0.6,
    "start_background_process": 0.6,
    "get_process_logs":      0.6,
    "kill_process":          0.6,
    "search_files":          0.6,
    "web_click":             0.6,

    # Interactive / text input — dynamic content
    "type_text":             0.4,
    "web_type":              0.4,
    "web_get_state":         0.4,

    # Positional / visual — highly volatile
    "click":                 0.3,
    "scroll":                0.3,
    "find_element":          0.3,
    "web_wait_for":          0.3,
    "web_scroll":            0.3,
}

DEFAULT_TOOL_STABILITY: float = 0.5

# ─────────────────────────────────────────────────────────────────────────────
# Parameter volatility patterns — any match deducts PARAMETER_PENALTY
# ─────────────────────────────────────────────────────────────────────────────
VOLATILE_PATTERNS: List[str] = [
    r'\$\w+',               # $variable_reference
    r'\{[^}]+\}',           # {template_placeholder}
    r'context\.',           # context.some_variable
    r'<[^>]+>',             # <placeholder>
    r'^\.\.',               # relative path traversal (..)
    r'^[^/\\:]+\.[a-z]+$',  # bare filename with no root (e.g. "modulo.py")
    r'^\s*$',               # empty string value
]

PARAMETER_PENALTY: float = 0.3


def _has_volatile_params(parameters: Dict[str, Any]) -> bool:
    """
    Returns True if any parameter value matches a volatile pattern.
    Only penalizes once per step regardless of how many params are volatile.
    """
    if not parameters:
        return False

    params_str = json.dumps(parameters, ensure_ascii=False)

    for pattern in VOLATILE_PATTERNS:
        if re.search(pattern, params_str):
            return True

    return False


def score_step(tool_name: str, parameters: Dict[str, Any]) -> float:
    """
    Score a single step [0.0 – 1.0].
    Base score from TOOL_STABILITY, reduced by PARAMETER_PENALTY if
    the parameters contain volatile/dynamic values.
    """
    base = TOOL_STABILITY.get(tool_name, DEFAULT_TOOL_STABILITY)

    if _has_volatile_params(parameters):
        base = max(0.0, base - PARAMETER_PENALTY)

    return round(base, 3)


def score_episode(step_results: List[Dict[str, Any]]) -> float:
    """
    Compute the episode-level stability score as the average of all step scores.

    step_results format (same as microplanner step_results list):
        [{"action": str, "parameters": dict, ...}, ...]

    Returns a float in [0.0, 1.0]. Defaults to 0.5 for empty sequences.
    """
    if not step_results:
        return 0.5

    scores = []
    for step in step_results:
        tool_name = step.get("action", "")
        parameters = step.get("parameters", {})
        scores.append(score_step(tool_name, parameters))

    episode_score = sum(scores) / len(scores)
    return round(episode_score, 3)
