"""
File creation and editing tools.
Atomic writes. Line-ending preservation.
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from ....core.config import ActionResult
from ...context import ExecutionContext
from .guardrails import validate_path_safe


def _detect_line_ending(raw_bytes:bytes) -> str:
    """Detect the dominant line ending in a file's raw bytes"""
    crlf = raw_bytes.count(b"\r\n")
    lf = raw_bytes.count(b"\n") -crlf

    return "\r\n" if crlf > lf else "\n"

def _atomic_write(path: Path, content: str, newline: str = None) -> None:
    """
    Write to a temp file in the same
    directory then os.replace() it in.
    During a crash, does not effect the original.
    """

    fd, temp_path = tempfile.mkstemp(
        dir = str(path.parent),
        prefix=f".{path.stem}_",
        suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", 
                       newline=newline or "") as f:
            f.write(content)
        os.replace(temp_path, str(path))
    except:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise

# create_file_or_folder

CREATE_SCHEMA = {
    "path": {"type": "str", "required": True},
    "is_dir": {"type": "bool", "required": False, "default": False},
    "content": {"type": "str", "required": False, "default": ""}
}

def create_validate(params):
    path = params.get("path")
    if not path:
        return (False, "Missing 'path' parameter")
    valid, err, resolved = validate_path_safe(path, allow_write= True)
    if not valid:
        return (False, err)
    if resolved.exists():
        return (False, f"Already Exists: {resolved}")
    return (True, None)

def create_execute(params, context):
    _,_,path = validate_path_safe(params["path"], allow_write=True)
    is_dir = params.get("is_dir", False)
    content = params.get("content", "")

    try:
        if is_dir:
            path.mkdir(parents=True, exist_ok=True)
            return ActionResult(
                success = True,
                data={"path":str(path), "type":"directory"},
                method_used="filesystem"
            )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, content)
            return ActionResult(
                success=True,
                data={"path":str(path), "type":"file","size":len(content)},
                method_used="filesystem"
            )
    except PermissionError:
        return ActionResult(
            success=False, error=f"Permission denied: {path}",
            error_code="permission_denied", method_used="filesystem"
        )
    except Exception as e:
        return ActionResult(
            success=False, error=str(e), method_used="filesystem"
        )

# write_to_file

WRITE_SCHEMA = {
    "path": {"type": "str", "required": True},
    "content": {"type": "str", "required": True},
    "mode": {"type": "str", "required": False, "default": "append",
             "description": "write|append|overwrite"},
}

def write_validate(params):
    if not params.get("path"):
        return (False, "Missing 'path' parameter")
    if "content" not in params:
        return (False, "Missing 'content' parameter")
    mode = params.get("mode", "append")
    if mode not in ("write", "append", "overwrite"):
        return (False, f"Invalid mode: '{mode}'")
    valid, err, _ = validate_path_safe(params["path"], allow_write=True)
    return (valid, err) if not valid else (True, None)

def write_execute(params, context):
    _, _, path = validate_path_safe(params["path"], allow_write=True)
    content = str(params["content"])
    mode = params.get("mode", "append")
    
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        
        if mode == "append":
            # Append can't use atomic write (we don't want to rewrite the file)
            with open(path, "a", encoding="utf-8", newline="") as f:
                f.write(content)
        else:
            # write / overwrite → atomic
            _atomic_write(path, content)
        
        size = path.stat().st_size
        
        return ActionResult(
            success=True,
            data={"path": str(path), "mode": mode,
                  "bytes_written": len(content.encode("utf-8")),
                  "total_size": size},
            method_used="filesystem"
        )
    except PermissionError:
        return ActionResult(
            success=False, error=f"Permission denied: {path}",
            error_code="permission_denied", method_used="filesystem"
        )
    except Exception as e:
        return ActionResult(
            success=False, error=str(e), method_used="filesystem"
        )

# edit_file_by_lline 

EDIT_BY_LINES_SCHEMA = {
    "path": {"type": "str", "required": True},
    "start_line": {"type": "int", "required": True,
                   "description": "First line to replace (1-indexed, inclusive)"},
    "end_line": {"type": "int", "required": True,
                 "description": "Last line to replace (1-indexed, inclusive)"},
    "new_content": {"type": "str", "required": True,
                    "description": "Replacement content"},
}

def edit_by_lines_validate(params):
    for f in ("path", "start_line","end_line","new_content"):
        if f not in params:
            return (False, f"Missing '{f}' parameter")

    start = int(params["start_line"])
    end = int(params["end_line"])

    if start <1:
        return (False, "start_line must be >=1")
    if end<start:
        return (False, "end_line must be>=start_line")

    valid,err,_= validate_path_safe(
        params["path"], must_exist=True, allow_write= True
    )
    return (valid, err) if not valid else (True, None)

def edit_by_lines_execute(params, context):
    """
    Replace lines [start, end] inclusive with new_content.
    
    1. Reads with newline="" (preserves CRLF/LF exactly)
    2. Detects the file's line ending convention
    3. Writes atomically via tempfile + os.replace()
    """
    _, _, path = validate_path_safe(
        params["path"], must_exist=True, allow_write=True
    )
    start = int(params["start_line"])
    end = int(params["end_line"])
    new_content = str(params["new_content"])
    
    try:
        raw = path.read_bytes()
        line_ending = _detect_line_ending(raw)
        
        with open(path, "r", encoding="utf-8", newline="") as f:
            lines = f.readlines()
        
        total = len(lines)
        if start > total:
            return ActionResult(
                success=False,
                error=f"start_line {start} > file length ({total})",
                error_code="validation_error", method_used="filesystem"
            )
        end = min(end, total)
        
        old_content = "".join(lines[start - 1:end])
        
        new_lines = new_content.splitlines(keepends=True)
        
        normalized = []
        for nl in new_lines:
            stripped = nl.rstrip("\r\n")
            normalized.append(stripped + line_ending)
        
        if lines and not lines[-1].endswith(("\n", "\r")):
            if end == total and normalized:
                normalized[-1] = normalized[-1].rstrip("\r\n")
        
        result_lines = lines[:start - 1] + normalized + lines[end:]
        full_content = "".join(result_lines)
        
        _atomic_write(path, full_content, newline="")
        
        return ActionResult(
            success=True,
            data={
                "path": str(path),
                "start_line": start,
                "end_line": end,
                "lines_replaced": end - start + 1,
                "new_line_count": len(normalized),
                "old_content_preview": old_content[:200],
                "new_total_lines": len(result_lines),
                "line_ending": repr(line_ending),
            },
            method_used="filesystem"
        )
    except PermissionError:
        return ActionResult(
            success=False, error=f"Permission denied: {path}",
            error_code="permission_denied", method_used="filesystem"
        )
    except UnicodeDecodeError:
        return ActionResult(
            success=False, error="Cannot decode file (likely binary)",
            error_code="decode_error", method_used="filesystem"
        )
    except Exception as e:
        return ActionResult(
            success=False, error=str(e), method_used="filesystem"
        )
