"""
Bridge between system tools and the GuardrailsManager.
All safety checks go through here.
"""

import os
from pathlib import Path
from typing import Optional, Tuple

from ....security.guardrails_manager import get_guardrails

def validate_command_safe(command: str) -> Tuple[bool, Optional[str]]:
    """Validate a shell command against the signed allowlist."""
    return get_guardrails().validate_command(command)

def validate_path_safe(path_str: str,
                       must_exist: bool = False,
                       allow_write: bool = False) -> Tuple[bool, Optional[str], Optional[Path]]:
    """
    Validate a file path.
    
    For writes: checks against the project-root allowlist.
    For reads: only checks existence (no write-root restriction).
    """
    if not path_str or not path_str.strip():
        return (False, "Path cannot be empty", None)
    
    try:
        path = Path(path_str).resolve()
    except (ValueError, OSError) as e:
        return (False, f"Invalid path: {e}", None)
    
    if allow_write:
        ok, reason = get_guardrails().validate_write_path(path)
        if not ok:
            return (False, reason, None)
    
    if must_exist and not path.exists():
        return (False, f"Path does not exist: {path}", None)
    
    return (True, None, path)

def truncate_output(text: str, max_chars: int = None) -> Tuple[str, bool]:
    """Truncate text. Uses config limit if max_chars not specified."""
    if max_chars is None:
        max_chars = get_guardrails().rules.max_shell_output_chars
    if len(text) <= max_chars:
        return (text, False)
    return (text[:max_chars] + f"\n... [truncated, {len(text)} total chars]", True)

def should_skip_dir(name: str) -> bool:
    return get_guardrails().should_skip_directory(name)

def is_binary_file(path: Path) -> bool:
    return get_guardrails().is_binary_extension(path)

def get_limits():
    """Get current limits from the guardrails config."""
    return get_guardrails().rules
