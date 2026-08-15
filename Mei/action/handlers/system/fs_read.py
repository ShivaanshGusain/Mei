"""
File reading and searching tools.
All outputs are aggressively truncated for SLM context windows.
"""

import os
import re
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
 
from ....core.config import ActionResult
from ...context import ExecutionContext
from .guardrails import validate_path_safe, should_skip_dir, is_binary_file, get_limits
 

 
LIST_FILES_SCHEMA = {
    "path": {"type": "str", "required": True,
             "description": "Directory path to list"},
    "recursive": {"type": "bool", "required": False, "default": False,
                  "description": "List subdirectories recursively"},
    "show_hidden": {"type": "bool", "required": False, "default": False,
                    "description": "Include hidden files/folders"},
}
 
def list_files_validate(params):
    path = params.get("path")
    if not path:
        return (False, "Missing 'path' parameter")
    valid, err, resolved = validate_path_safe(path, must_exist=True)
    if not valid:
        return (False, err)
    if not resolved.is_dir():
        return (False, f"Not a directory: {resolved}")
    return (True, None)
 
def list_files_execute(params, context):
    path_str = params["path"]
    recursive = params.get("recursive", False)
    show_hidden = params.get("show_hidden", False)
 
    _, _, path = validate_path_safe(path_str, must_exist=True)
    limits = get_limits()
 
    entries = []
    count = 0
    truncated = False
 
    try:
        if recursive:
            for root, dirs, files in os.walk(path):
                # Filter out junk directories in-place
                dirs[:] = [d for d in dirs
                          if not should_skip_dir(d)
                          and (show_hidden or not d.startswith("."))]
 
                rel_root = Path(root).relative_to(path)
 
                for f in sorted(files):
                    if not show_hidden and f.startswith("."):
                        continue
                    if count >= limits.max_list_entries:
                        truncated = True
                        break
 
                    fp = Path(root) / f
                    try:
                        size = fp.stat().st_size
                    except OSError:
                        size = -1
                    entries.append({
                        "name": str(rel_root / f),
                        "type": "file",
                        "size": size,
                    })
                    count += 1
 
                if truncated:
                    break
        else:
            for item in sorted(path.iterdir()):
                name = item.name
                if not show_hidden and name.startswith("."):
                    continue
                if should_skip_dir(name) and item.is_dir():
                    continue
                if count >= limits.max_list_entries:
                    truncated = True
                    break
 
                entry = {
                    "name": name,
                    "type": "dir" if item.is_dir() else "file",
                }
                if item.is_file():
                    try:
                        entry["size"] = item.stat().st_size
                    except OSError:
                        entry["size"] = -1
                elif item.is_dir():
                    # ── Capped child count (v2) ──
                    # Stop counting past list_children_cap rather than
                    # doing a full iterdir() walk purely for a display number.
                    try:
                        child_count = 0
                        for _ in item.iterdir():
                            child_count += 1
                            if child_count >= limits.list_children_cap:
                                break
                        entry["children"] = (
                            f"{limits.list_children_cap}+"
                            if child_count >= limits.list_children_cap
                            else child_count
                        )
                    except PermissionError:
                        entry["children"] = "?"
 
                entries.append(entry)
                count += 1
 
        return ActionResult(
            success=True,
            data={
                "path": str(path),
                "entries": entries,
                "count": len(entries),
                "truncated": truncated,
            },
            method_used="filesystem"
        )
    except PermissionError:
        return ActionResult(
            success=False,
            error=f"Permission denied: {path}",
            error_code="permission_denied",
            method_used="filesystem"
        )
    except FileNotFoundError:
        return ActionResult(
            success=False,
            error=f"Path not found: {path}",
            error_code="not_found",
            method_used="filesystem"
        )
    except Exception as e:
        return ActionResult(success=False, error=str(e), method_used="filesystem")
 
 
# ═══════════════════════════════════════════════════
# read_file
# ═══════════════════════════════════════════════════
 
READ_FILE_SCHEMA = {
    "path": {"type": "str", "required": True,
             "description": "File path to read"},
    "start_line": {"type": "int", "required": False, "default": 1,
                   "description": "First line to read (1-indexed)"},
    "max_lines": {"type": "int", "required": False, "default": 100,
                  "description": "Maximum lines to return"},
    "tail": {"type": "bool", "required": False, "default": False,
             "description": "Read from end of file instead of start_line"},
}
 
def read_file_validate(params):
    path = params.get("path")
    if not path:
        return (False, "Missing 'path' parameter")
    valid, err, resolved = validate_path_safe(path, must_exist=True)
    if not valid:
        return (False, err)
    if not resolved.is_file():
        return (False, f"Not a file: {resolved}")
    if is_binary_file(resolved):
        return (False, f"Cannot read binary file: {resolved.name}")
    return (True, None)
 
def read_file_execute(params, context):
    path_str = params["path"]
    limits = get_limits()
 
    # Defensive coercion — planner params can arrive as strings.
    try:
        start_line = max(1, int(params.get("start_line", 1)))
    except (TypeError, ValueError):
        start_line = 1
    try:
        max_lines = min(int(params.get("max_lines", 100)), limits.max_file_read_lines)
    except (TypeError, ValueError):
        max_lines = min(100, limits.max_file_read_lines)
    tail = bool(params.get("tail", False))
 
    _, _, path = validate_path_safe(path_str, must_exist=True)
 
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
 
        total_lines = len(all_lines)
 
        if tail:
            # Read last N lines
            selected = all_lines[-max_lines:]
            first_line_num = max(1, total_lines - max_lines + 1)
        else:
            # Read from start_line
            start_idx = start_line - 1
            selected = all_lines[start_idx:start_idx + max_lines]
            first_line_num = start_line
 
        # Format with line numbers
        numbered_lines = []
        for i, line in enumerate(selected):
            line_num = first_line_num + i
            numbered_lines.append(f"{line_num}: {line.rstrip()}")
 
        content = "\n".join(numbered_lines)
 
        return ActionResult(
            success=True,
            data={
                "path": str(path),
                "content": content,
                "start_line": first_line_num,
                "end_line": first_line_num + len(selected) - 1 if selected else first_line_num,
                "total_lines": total_lines,
                "lines_returned": len(selected),
                "has_more": (first_line_num + len(selected) - 1) < total_lines,
            },
            method_used="filesystem"
        )
    except UnicodeDecodeError:
        return ActionResult(
            success=False,
            error=f"Cannot decode file (likely binary): {path.name}",
            error_code="decode_error",
            method_used="filesystem"
        )
    except PermissionError:
        return ActionResult(
            success=False,
            error=f"Permission denied: {path}",
            error_code="permission_denied",
            method_used="filesystem"
        )
    except FileNotFoundError:
        return ActionResult(
            success=False,
            error=f"File not found: {path}",
            error_code="not_found",
            method_used="filesystem"
        )
    except Exception as e:
        return ActionResult(success=False, error=str(e), method_used="filesystem")
 
 
# ═══════════════════════════════════════════════════
# search_files
# ═══════════════════════════════════════════════════
 
SEARCH_FILES_SCHEMA = {
    "directory": {"type": "str", "required": True,
                  "description": "Directory to search in"},
    "pattern": {"type": "str", "required": True,
                "description": "Text or regex pattern to search for"},
    "file_glob": {"type": "str", "required": False, "default": "*",
                  "description": "File glob filter (e.g. '*.py', '*.js')"},
    "is_regex": {"type": "bool", "required": False, "default": False,
                 "description": "Treat pattern as regex"},
}
 
def search_files_validate(params):
    if not params.get("directory"):
        return (False, "Missing 'directory' parameter")
    if not params.get("pattern"):
        return (False, "Missing 'pattern' parameter")
    valid, err, _ = validate_path_safe(params["directory"], must_exist=True)
    if not valid:
        return (False, err)
    if params.get("is_regex"):
        try:
            re.compile(str(params["pattern"]))
        except re.error as e:
            return (False, f"Invalid regex: {e}")
    return (True, None)
 
def search_files_execute(params, context):
    dir_str = params["directory"]
    pattern = str(params["pattern"])
    file_glob = params.get("file_glob", "*")
    is_regex = bool(params.get("is_regex", False))
 
    _, _, directory = validate_path_safe(dir_str, must_exist=True)
    limits = get_limits()
 
    if is_regex:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return ActionResult(
                success=False,
                error=f"Invalid regex: {e}",
                error_code="validation_error",
                method_used="filesystem"
            )
 
    matches = []
    files_searched = 0
 
    try:
        for root, dirs, files in os.walk(directory):
            # ── Filter junk directories in-place ──
            dirs[:] = [d for d in dirs if not should_skip_dir(d)]
 
            for filename in files:
                filepath = Path(root) / filename
 
                # Skip binary files
                if is_binary_file(filepath):
                    continue
 
                # Apply glob filter
                if file_glob != "*" and not filepath.match(file_glob):
                    continue
 
                files_searched += 1
 
                # Search file content
                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        for line_num, line in enumerate(f, 1):
                            found = False
                            if is_regex:
                                found = bool(regex.search(line))
                            else:
                                found = pattern.lower() in line.lower()
 
                            if found:
                                matches.append({
                                    "file": str(filepath.relative_to(directory)),
                                    "line": line_num,
                                    "content": line.strip()[:200],
                                })
 
                                if len(matches) >= limits.max_search_results:
                                    return ActionResult(
                                        success=True,
                                        data={
                                            "matches": matches,
                                            "match_count": len(matches),
                                            "files_searched": files_searched,
                                            "truncated": True,
                                            "pattern": pattern,
                                        },
                                        method_used="filesystem"
                                    )
                except (PermissionError, UnicodeDecodeError):
                    continue
 
        return ActionResult(
            success=True,
            data={
                "matches": matches,
                "match_count": len(matches),
                "files_searched": files_searched,
                "truncated": False,
                "pattern": pattern,
            },
            method_used="filesystem"
        )
    except PermissionError:
        return ActionResult(
            success=False,
            error=f"Permission denied: {directory}",
            error_code="permission_denied",
            method_used="filesystem"
        )
    except Exception as e:
        return ActionResult(success=False, error=str(e), method_used="filesystem")