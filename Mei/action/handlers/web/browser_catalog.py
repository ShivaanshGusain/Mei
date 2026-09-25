"""
Browser discovery and selection for the web/* handlers.

Two layers:
  1. Discovery : find installed browsers from what Windows already knows
                 about them (registry browser-client/association
                 registrations + a manual override) — no hardcoded install
                 paths or fixed browser list.
  2. Selection : match a user's request against the discovered catalog,
                 without ever guessing/inventing an executable name.

session.py (execution layer) turns a Selection into an actual CDP session;
app.py turns a Selection into either a CDP session or a plain process launch.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import time
import winreg
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ....core.config import get_config

# A hint, not an allowlist. Our automation layer currently only knows how to
# drive browsers over Chromium's `--remote-debugging-port` + Playwright's
# connect_over_cdp(). A browser whose exe isn't in this set is still
# discovered and can still be opened normally — cdp_hint just means "not yet
# recognized by our current web-automation integration", not "incapable".
_CDP_CAPABLE_EXE_HINTS = {
    "chrome.exe", "msedge.exe", "brave.exe", "opera.exe", "opera_gx.exe",
    "vivaldi.exe", "chromium.exe", "browser.exe",
}

# Optional convenience aliases — enrich matching_names, never define identity.
_BROWSER_ALIASES = {
    "chrome": "chrome.exe", "google chrome": "chrome.exe",
    "edge": "msedge.exe", "microsoft edge": "msedge.exe",
    "brave": "brave.exe", "brave browser": "brave.exe",
    "firefox": "firefox.exe", "mozilla firefox": "firefox.exe",
    "opera": "opera.exe", "vivaldi": "vivaldi.exe",
}

_CHANNEL_HINTS = ["canary", "beta", "dev", "developer", "nightly"]

NOT_FOUND = "not_found"
AMBIGUOUS = "ambiguous"
NEEDS_CONFIRMATION = "needs_confirmation"
SELECTED = "selected"

_CATALOG_TTL_SECONDS = 300


@dataclass
class BrowserRecord:
    id: str                       # deterministic — derived from the real exe path, not enumeration order
    display_name: str
    exe_path: str
    exe_name: str
    matching_names: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    channel: str = "stable"
    cdp_hint: bool = False


@dataclass
class Selection:
    outcome: str
    record: Optional[BrowserRecord] = None
    candidates: List[BrowserRecord] = field(default_factory=list)


def _normalize(text: str) -> str:
    cleaned = " ".join(text.lower().strip().split())
    for suffix in (" browser", " application", " app"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
    if cleaned.endswith(".exe"):
        cleaned = cleaned[:-4]
    return cleaned


def _detect_channel(candidate_id: str, display_name: str, exe_basename: str) -> str:
    joined = " ".join(t.lower() for t in (candidate_id, display_name, exe_basename) if t)
    for hint in _CHANNEL_HINTS:
        if hint in joined:
            return "dev" if hint in ("dev", "developer") else hint
    return "stable"


def _extract_exe_path(command_line: str) -> Optional[str]:
    """Pull the executable path out of a registry 'shell\\open\\command' string.
    We only ever read the path from here — the app always launches it with its
    own controlled arguments, never the registry's raw command line."""
    command_line = os.path.expandvars(command_line.strip())
    if command_line.startswith('"'):
        end = command_line.find('"', 1)
        if end != -1:
            return command_line[1:end]
    lower = command_line.lower()
    idx = lower.find(".exe")
    if idx != -1:
        return command_line[: idx + 4].strip()
    return command_line.split(" ")[0] if command_line else None


def _valid_exe(path: Optional[str]) -> Optional[str]:
    if path and os.path.isfile(path):
        return path
    return None


def _make_id(exe_path: str) -> str:
    real = os.path.normcase(os.path.realpath(exe_path))
    digest = hashlib.sha1(real.encode("utf-8", "ignore")).hexdigest()[:8]
    stem = os.path.splitext(os.path.basename(real))[0]
    return f"{stem}-{digest}"


def _make_record(candidate_id: str, display_name: str, exe_path: Optional[str], source: str) -> Optional[BrowserRecord]:
    """Builds a record strictly from the exe path this registration itself
    resolved to. An unresolved/invalid path means skip this registration —
    we never substitute a different executable to "repair" it."""
    exe_path = _valid_exe(exe_path)
    if not exe_path:
        return None

    exe_name = os.path.basename(exe_path).lower()
    matching_names = {candidate_id, display_name, exe_name[:-4] if exe_name.endswith(".exe") else exe_name}
    for alias, aliased_exe in _BROWSER_ALIASES.items():
        if aliased_exe == exe_name:
            matching_names.add(alias)

    return BrowserRecord(
        id=_make_id(exe_path),
        display_name=display_name or candidate_id,
        exe_path=exe_path,
        exe_name=exe_name,
        matching_names=sorted({m for m in matching_names if m}),
        sources=[source],
        channel=_detect_channel(candidate_id, display_name, exe_name),
        cdp_hint=exe_name in _CDP_CAPABLE_EXE_HINTS,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Discovery providers
# ─────────────────────────────────────────────────────────────────────────────

def _hklm_views():
    """(root, extra_view_flag) pairs covering both the 32-bit and 64-bit registry views."""
    return [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    ]


def _discover_start_menu_internet() -> List[BrowserRecord]:
    """Browser-client registrations — the strongest identity signal Windows exposes."""
    records: List[BrowserRecord] = []
    subkey = r"SOFTWARE\Clients\StartMenuInternet"

    for root, view_flag in _hklm_views():
        try:
            clients = winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | view_flag)
        except OSError:
            continue
        with clients:
            i = 0
            while True:
                try:
                    client_id = winreg.EnumKey(clients, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(clients, client_id, 0, winreg.KEY_READ | view_flag) as client_key:
                        try:
                            display_name, _ = winreg.QueryValueEx(client_key, None)
                        except OSError:
                            display_name = client_id
                        try:
                            with winreg.OpenKey(client_key, r"shell\open\command", 0, winreg.KEY_READ | view_flag) as cmd_key:
                                command, _ = winreg.QueryValueEx(cmd_key, None)
                        except OSError:
                            command = None
                except OSError:
                    continue

                record = _make_record(
                    client_id, display_name,
                    _extract_exe_path(command) if command else None,
                    "start_menu_internet",
                )
                if record:
                    records.append(record)
    return records


def _resolve_progid_exe(progid: str) -> Optional[str]:
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, fr"{progid}\shell\open\command") as key:
            command, _ = winreg.QueryValueEx(key, None)
            return _extract_exe_path(command)
    except OSError:
        return None


def get_os_default_progid() -> Optional[str]:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            progid, _ = winreg.QueryValueEx(key, "ProgId")
            return progid
    except OSError:
        return None


def get_os_default_exe_path() -> Optional[str]:
    progid = get_os_default_progid()
    if not progid:
        return None
    return _valid_exe(_resolve_progid_exe(progid))


def _discover_registered_applications() -> List[BrowserRecord]:
    """RegisteredApplications -> Capabilities -> URLAssociations\\http, for browsers
    that register their HTTP capability but aren't in StartMenuInternet."""
    records: List[BrowserRecord] = []
    for root, view_flag in _hklm_views():
        try:
            reg_apps = winreg.OpenKey(root, r"SOFTWARE\RegisteredApplications", 0, winreg.KEY_READ | view_flag)
        except OSError:
            continue
        with reg_apps:
            i = 0
            while True:
                try:
                    name, caps_path, _ = winreg.EnumValue(reg_apps, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, fr"{caps_path}\URLAssociations", 0, winreg.KEY_READ | view_flag) as assoc_key:
                        progid, _ = winreg.QueryValueEx(assoc_key, "http")
                except OSError:
                    continue

                record = _make_record(name, name, _resolve_progid_exe(progid), "url_association")
                if record:
                    records.append(record)
    return records


def _discover_manual() -> List[BrowserRecord]:
    """Config-supplied paths — the escape hatch for portable or unusual installs.
    Edit config.yaml's `preferences.manual_browsers: {name: path}` to add one.
    An invalid path here is reported and skipped, never substituted."""
    manual = get_config().preferences.get("manual_browsers", {})
    if not isinstance(manual, dict):
        return []
    records = []
    for name, path in manual.items():
        record = _make_record(name, name, path, "manual")
        if record:
            records.append(record)
        else:
            print(f"[BrowserCatalog] manual_browsers entry '{name}' -> '{path}' does not exist, skipping")
    return records


def _enumerate_app_paths() -> Dict[str, str]:
    """Last-resort exe-location lookup — used only if no registration provider
    above found anything at all (see discover_browsers())."""
    found: Dict[str, str] = {}
    subkey = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for root, view_flag in _hklm_views():
        try:
            app_paths = winreg.OpenKey(root, subkey, 0, winreg.KEY_READ | view_flag)
        except OSError:
            continue
        with app_paths:
            i = 0
            while True:
                try:
                    exe_name = winreg.EnumKey(app_paths, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(app_paths, exe_name) as entry:
                        path, _ = winreg.QueryValueEx(entry, None)
                        valid = _valid_exe(path)
                        if valid:
                            found[exe_name.lower()] = valid
                except OSError:
                    continue
    return found


def _dedupe(records: List[BrowserRecord]) -> Dict[str, BrowserRecord]:
    """IDs are already derived from the real exe path, so the same install gets
    the same id regardless of discovery order — this just merges evidence."""
    catalog: Dict[str, BrowserRecord] = {}
    for record in records:
        existing = catalog.get(record.id)
        if existing is None:
            catalog[record.id] = record
        else:
            existing.matching_names = sorted(set(existing.matching_names) | set(record.matching_names))
            existing.sources = sorted(set(existing.sources) | set(record.sources))
    return catalog


_catalog_cache: Optional[Dict[str, BrowserRecord]] = None
_catalog_cached_at: float = 0.0


def discover_browsers(force_refresh: bool = False) -> Dict[str, BrowserRecord]:
    """Builds the browser catalog from all discovery providers, cached briefly
    since registry scans aren't free and browsers don't get (un)installed mid-session."""
    global _catalog_cache, _catalog_cached_at
    if not force_refresh and _catalog_cache is not None and (time.monotonic() - _catalog_cached_at) < _CATALOG_TTL_SECONDS:
        return dict(_catalog_cache)

    records: List[BrowserRecord] = []
    records.extend(_discover_start_menu_internet())
    records.extend(_discover_registered_applications())
    records.extend(_discover_manual())

    catalog = _dedupe(records)

    if not catalog:
        # No registry browser-client/association registrations found at all
        # (unusual). Fall back to known chromium-family + Firefox App Paths
        # entries so the agent isn't left with zero options.
        for exe_name, path in _enumerate_app_paths().items():
            if exe_name in _CDP_CAPABLE_EXE_HINTS or exe_name == "firefox.exe":
                record = _make_record(exe_name, exe_name, path, "app_paths_fallback")
                if record:
                    catalog[record.id] = record

    _catalog_cache = catalog
    _catalog_cached_at = time.monotonic()
    return dict(catalog)


def get_os_default_record(catalog: Dict[str, BrowserRecord]) -> Optional[BrowserRecord]:
    default_path = get_os_default_exe_path()
    if not default_path:
        return None
    default_id = _make_id(default_path)
    if default_id in catalog:
        return catalog[default_id]
    # Default browser is real but wasn't picked up by any registration provider — still honor it.
    return _make_record(os.path.basename(default_path), os.path.basename(default_path), default_path, "url_association")


# ─────────────────────────────────────────────────────────────────────────────
# Selection
# ─────────────────────────────────────────────────────────────────────────────

def select_browser(query: str, catalog: Dict[str, BrowserRecord]) -> Selection:
    """
    Matches an explicit user request against the catalog. Only ever returns
    records the discovery layer found — never invents an executable name.

    Match                        Result
    unique exact normalized name SELECTED
    multiple exact matches       AMBIGUOUS
    substring or fuzzy matches   NEEDS_CONFIRMATION (candidates, no auto-pick)
    nothing                      NOT_FOUND
    """
    cleaned = _normalize(query)
    if not cleaned or not catalog:
        return Selection(outcome=NOT_FOUND, candidates=list(catalog.values()))

    name_to_records: Dict[str, List[BrowserRecord]] = {}
    for record in catalog.values():
        for n in record.matching_names:
            name_to_records.setdefault(_normalize(n), []).append(record)

    exact_hits = _unique(name_to_records.get(cleaned, []))
    if len(exact_hits) == 1:
        return Selection(SELECTED, record=exact_hits[0])
    if len(exact_hits) > 1:
        return Selection(AMBIGUOUS, candidates=exact_hits)

    substring_hits = _unique([
        r for name, records in name_to_records.items() if cleaned in name or name in cleaned
        for r in records
    ])
    if substring_hits:
        return Selection(NEEDS_CONFIRMATION, candidates=substring_hits)

    fuzzy_names = difflib.get_close_matches(cleaned, list(name_to_records.keys()), n=3, cutoff=0.75)
    fuzzy_hits = _unique([r for name in fuzzy_names for r in name_to_records[name]])
    if fuzzy_hits:
        return Selection(NEEDS_CONFIRMATION, candidates=fuzzy_hits)

    return Selection(NOT_FOUND, candidates=list(catalog.values()))


def _unique(records: List[BrowserRecord]) -> List[BrowserRecord]:
    seen = {}
    for r in records:
        seen[r.id] = r
    return list(seen.values())
