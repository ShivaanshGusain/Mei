"""
Working directory state management.
The cwd is stored in ExecutionContext.variables, not os.chdir() — the
process's real working directory is never touched, so this is safe to
call repeatedly from a ReAct loop without side effects on other tools.
"""
import os
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from ....core.config import ActionResult
from ...context import ExecutionContext
from .guardrails import validate_path_safe


# ═══════════════════════════════════════════════════
# change_directory
# ═══════════════════════════════════════════════════

CHANGE_DIR_SCHEMA = {
    "path": {"type": "str", "required": True,
             "description": "Directory path to change to"},
}

def change_dir_validate(params):
    path = params.get("path")
    if not path:
        return (False, "Missing 'path' parameter")
    valid, err, resolved = validate_path_safe(path, must_exist=True)
    if not valid:
        return (False, err)
    if not resolved.is_dir():
        return (False, f"Not a directory: {resolved}")
    return (True, None)

def change_dir_execute(params, context):
    valid, err, path = validate_path_safe(params["path"], must_exist=True)
    if not valid:
        return ActionResult(
            success=False,
            error=err,
            error_code="not_found",
            method_used="context"
        )

    old_cwd = context.get_variable("cwd", os.getcwd())
    context.set_variable("cwd", str(path))

    return ActionResult(
        success=True,
        data={
            "old_cwd": old_cwd,
            "new_cwd": str(path),
        },
        method_used="context"
    )


# ═══════════════════════════════════════════════════
# get_cwd
# ═══════════════════════════════════════════════════

GET_CWD_SCHEMA = {}

def get_cwd_validate(params):
    return (True, None)

def get_cwd_execute(params, context):
    cwd = context.get_variable("cwd", os.getcwd())

    return ActionResult(
        success=True,
        data={
            "cwd": cwd,
            "exists": Path(cwd).exists(),
        },
        method_used="context"
    )