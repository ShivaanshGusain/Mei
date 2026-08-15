"""File management — trash deletion, move, download with size enforcement."""
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from ....core.config import ActionResult
from ....core.events import emit, EventType
from ...context import ExecutionContext
from .guardrails import validate_path_safe, get_limits



DELETE_PATH_SCHEMA = {
    "path": {"type": "str", "required": True},
    "confirm": {"type": "bool", "required": False, "default": False,
                "description": "Must be true to delete"},
}

def delete_path_validate(params):
    path = params.get("path")
    if not path:
        return (False, "Missing 'path' parameter")
    valid, err, resolved = validate_path_safe(
        path, must_exist=True, allow_write=True
    )
    if not valid:
        return (False, err)
    if not params.get("confirm", False):
        return (False, f"Set confirm=true to delete: {resolved}")
    return (True, None)

def delete_path_execute(params, context):
    _, _, path = validate_path_safe(
        params["path"], must_exist=True, allow_write=True
    )
    
    try:
        from send2trash import send2trash
    except ImportError:
        return ActionResult(
            success=False,
            error="send2trash not installed. pip install send2trash. "
                  "Refusing permanent deletion.",
            error_code="blocked", method_used="filesystem"
        )
    
    try:
        is_dir = path.is_dir()
        send2trash(str(path))
        
        return ActionResult(
            success=True,
            data={
                "path": str(path),
                "type": "directory" if is_dir else "file",
                "method": "recycle_bin",
                "recoverable": True,
            },
            method_used="send2trash"
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


RENAME_MOVE_SCHEMA = {
    "source": {"type": "str", "required": True},
    "destination": {"type": "str", "required": True},
}

def rename_move_validate(params):
    if not params.get("source"):
        return (False, "Missing 'source'")
    if not params.get("destination"):
        return (False, "Missing 'destination'")
    valid, err, _ = validate_path_safe(params["source"], must_exist=True)
    if not valid:
        return (False, f"Source: {err}")
    valid, err, _ = validate_path_safe(
        params["destination"], allow_write=True
    )
    if not valid:
        return (False, f"Destination: {err}")
    return (True, None)

def rename_move_execute(params, context):
    _, _, source = validate_path_safe(params["source"], must_exist=True)
    _, _, dest = validate_path_safe(params["destination"], allow_write=True)
    
    try:
        if dest.is_dir():
            dest = dest / source.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        
        return ActionResult(
            success=True,
            data={"source": str(source), "destination": str(dest)},
            method_used="filesystem"
        )
    except PermissionError:
        return ActionResult(
            success=False, error=f"Permission denied",
            error_code="permission_denied", method_used="filesystem"
        )
    except Exception as e:
        return ActionResult(
            success=False, error=str(e), method_used="filesystem"
        )


DOWNLOAD_FILE_SCHEMA = {
    "url": {"type": "str", "required": True},
    "destination": {"type": "str", "required": True},
}

def download_file_validate(params):
    if not params.get("url"):
        return (False, "Missing 'url'")
    if not params.get("destination"):
        return (False, "Missing 'destination'")
    url = str(params["url"]).strip()
    if not url.startswith(("http://", "https://")):
        return (False, "URL must start with http:// or https://")
    valid, err, _ = validate_path_safe(
        params["destination"], allow_write=True
    )
    return (valid, err) if not valid else (True, None)

def download_file_execute(params, context):
    import requests
    
    url = str(params["url"]).strip()
    _, _, dest = validate_path_safe(params["destination"], allow_write=True)
    max_bytes = get_limits().max_download_size_mb * 1024 * 1024
    
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        
        # ── Check Content-Length header (advisory) ──
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            return ActionResult(
                success=False,
                error=f"File too large: {int(content_length) / 1024 / 1024:.1f}MB "
                      f"(limit: {get_limits().max_download_size_mb}MB)",
                error_code="size_limit", method_used="requests"
            )
        
        total = 0
        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                total += len(chunk)
                if total > max_bytes:
                    f.close()
                    try:
                        os.unlink(str(dest))
                    except OSError:
                        pass
                    return ActionResult(
                        success=False,
                        error=f"Download aborted at {total / 1024 / 1024:.1f}MB "
                              f"(limit: {get_limits().max_download_size_mb}MB). "
                              f"Content-Length header was "
                              f"{'missing' if not content_length else 'inaccurate'}.",
                        error_code="size_limit", method_used="requests"
                    )
                f.write(chunk)
        
        return ActionResult(
            success=True,
            data={
                "url": url, "destination": str(dest),
                "size_bytes": total,
                "content_type": response.headers.get("Content-Type", "unknown"),
            },
            method_used="requests"
        )
    except requests.exceptions.Timeout:
        return ActionResult(
            success=False, error="Download timed out (30s)",
            error_code="timeout", method_used="requests"
        )
    except requests.exceptions.HTTPError as e:
        return ActionResult(
            success=False, error=f"HTTP error: {e}",
            error_code="connection_error", method_used="requests"
        )
    except Exception as e:
        return ActionResult(
            success=False, error=str(e), method_used="requests"
        )