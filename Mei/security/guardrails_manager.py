"""
Runtime guardrails manager. Singleton
"""

import shlex
import re
import threading
from pathlib import Path
from typing import Optional, Tuple, Set, List, Dict, Any, FrozenSet
from dataclasses import dataclass, field

from .loader import load_and_verify

@dataclass(frozen=True)
class GuardrailRuleset:
    allowed_executables: FrozenSet[str] = frozenset()
    blocked_shell_operators: FrozenSet[str] = frozenset({
        "&&", "||", ";", "`", "$(", ">>", ">", "<", "|",
    })
    allow_chaining: bool = False                              # NEW
    restricted_flags: Dict[str, FrozenSet[str]] = field(       # NEW
        default_factory=dict
    )

    allowed_write_roots: tuple = () 
    protected_paths: tuple = ()

    binary_extensions: FrozenSet[str] = frozenset()
    skip_directories: FrozenSet[str] = frozenset()

    # Limits
    max_shell_output_chars: int = 5000
    max_file_read_lines: int = 200
    max_search_results: int = 30
    max_list_entries: int = 100
    max_concurrent_processes: int = 2
    max_shell_timeout_seconds: int = 60
    max_download_size_mb: int = 100
    early_output_wait_seconds: float = 2.0
    max_log_lines: int = 500
    list_children_cap: int = 100

    config_version: int = 0
    is_default: bool = True


def _build_ruleset(config:Dict[str,Any])->GuardrailRuleset:
    """Build an immutable ruleset from a verified config dict."""

    limits = config.get("limits",{})

    # Resolve write root to absolute Paths
    write_root = tuple(
        Path(p).resolve()
        for p in config.get("allowed_write_roots",[])
    )
    protected = tuple(
        Path(p).resolve()
        for p in config.get("protected_paths", [])
    )
    restricted = {
        exe.lower(): frozenset(flags)
        for exe, flags in config.get("restricted_flags", {}).items()
    }

    return GuardrailRuleset(
        allowed_executables=frozenset(e.lower() for e in config.get("allowed_executables",[])),
        blocked_shell_operators=frozenset(config.get("blocked_shell_operators", [])),
        allow_chaining=config.get("allow_chaining", False),

        restricted_flags=restricted,
        protected_paths=protected,
        binary_extensions=frozenset(
            config.get("binary_extensions", [])
        ),
        skip_directories=frozenset(
            config.get("skip_directories", [])
        ),
        max_shell_output_chars=limits.get("max_shell_output_chars", 10000),
        max_file_read_lines=limits.get("max_file_read_lines", 500),
        max_search_results=limits.get("max_search_results", 50),
        max_list_entries=limits.get("max_list_entries", 200),
        max_concurrent_processes=limits.get("max_concurrent_processes", 3),
        max_shell_timeout_seconds=limits.get("max_shell_timeout_seconds", 120),
        max_download_size_mb=limits.get("max_download_size_mb", 500),
        early_output_wait_seconds=limits.get("early_output_wait_seconds", 2.0),
        max_log_lines=limits.get("max_log_lines", 500),
        list_children_cap=limits.get("list_children_cap", 100),
        config_version=config.get("version", 0),
        is_default=False,
    )


class GuardrailsManager:
    """
    Singleton, provides validation methods against the current ruleset.
    Thread safe via atomic reference swap.
    """

    def __init__(self):
        self._ruleset: GuardrailRuleset = GuardrailRuleset()
        self._load_lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        """Load and verify config. On failure, keep current ruleset."""
        success,config, reason = load_and_verify()

        if success and config:
            new_ruleset = _build_ruleset(config)

            self._ruleset = new_ruleset
            print(f"[Guardrails] Loaded config v{new_ruleset.config_version}")

        else:
            print(f"[Guardrails] FAIL-CLOSED: {reason}")
            print(f"[Guardrails] Using minimal-safe defaults "
                  f"(no commands, no writes)")

    def reload(self) -> Tuple[bool,str]:
        with self._load_lock:
            success, config, reason = load_and_verify()

            if not success or not config:
                return (False, f"Reload failed ( keeping current rules ): {reason}")

            new_ruleset = _build_ruleset(config)

            self._ruleset = new_ruleset
            return (True, f"Reloaded config v{new_ruleset.config_version}")

    @property
    def rules(self)-> GuardrailRuleset:
        """Current ruleset ( immutable snapshot )"""
        return self._ruleset

    def validate_command(self,command:str)-> Tuple[bool, Optional[str]]:
        """
        Validate a shell command against the allowlist.
        
        Process:
        1. Check for blocked shell operators in the raw string
        2. Parse with shlex.split()
        3. Check first token (executable) against allowlist
        """
        rules = self._ruleset
        raw = command.strip()
        if not raw:
            return (False, "Empty command")

        always_blocked = rules.blocked_shell_operators - {"&&"}
        for op in always_blocked:
            if op in raw:
                return (False, f"Operator '{op}' is never permitted")

        #Split on "&&" only if chaining is enabled ──
        if "&&" in raw:
            if not rules.allow_chaining:
                return (False, "Command chaining ('&&') is disabled")
            segments = [s.strip() for s in raw.split("&&")]
        else:
            segments = [raw]

        for segment in segments:
            ok, reason = self._validate_single(segment)
            if not ok:
                return (False, f"'{segment}': {reason}")

        return (True, None)

    def _validate_single(self, segment: str) -> Tuple[bool, Optional[str]]:
        rules = self._ruleset
        try:
            tokens = shlex.split(segment, posix=False)
        except ValueError as e:
            return (False, f"Cannot parse: {e}")
        if not tokens:
            return (False, "No executable found")

        executable = Path(tokens[0].lower()).stem.lower()
        if executable not in rules.allowed_executables:
            return (False, f"'{executable}' not in allowlist")

        blocked_flags = rules.restricted_flags.get(executable, frozenset())
        for tok in tokens[1:]:
            if tok.lower() in blocked_flags:
                return (False, f"Flag '{tok}' is restricted for '{executable}'")

        return (True, None)

    def validate_write_path(self, path: Path)-> Tuple[bool, Optional[str]]:
        """Check if a path is inside an allowed write root."""
        rules = self._ruleset
        resolved = path.resolve()

        for protected in rules.protected_paths:
            try:
                if resolved == protected or protected in resolved.parents:
                    return (False, f"Protected path: {protected}")
            except (ValueError, OSError):
                pass

        for root in rules.allowed_write_roots:
            try:
                resolved.relative_to(root)
                return (True, None)
            except ValueError:
                continue
        return (False, f"Path '{resolved}' is outside all allowed write roots: "
                f"{[str(r) for r in rules.allowed_write_roots]}")

    def is_binary_extension(self, path:Path)-> bool:
        return path.suffix.lower() in self._ruleset.binary_extensions

    def should_skip_directory(self, name:str)->bool:
        return name in self._ruleset.skip_directories

_manager: Optional[GuardrailsManager] = None
_init_lock = threading.Lock()

def get_guardrails() -> GuardrailsManager:
    global _manager
    if _manager is None:
        with _init_lock:
            if _manager is None:
                _manager = GuardrailsManager()

    return _manager