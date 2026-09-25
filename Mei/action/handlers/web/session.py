"""
Singleton manager for a Playwright browser session over CDP

Connects once to an already-running browser at
localhost:9222.
All web tools as this manager for active page.
"""

import os
import threading
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright

from ....core.config import get_config
from ....core.events import emit, EventType
from .browser_catalog import (
    BrowserRecord, discover_browsers, select_browser, get_os_default_record,
    SELECTED, AMBIGUOUS, NEEDS_CONFIRMATION,
)


def get_preferred_browser_id() -> Optional[str]:
    return get_config().preferences.get("browser_id")


def set_preferred_browser(record: BrowserRecord) -> None:
    config = get_config()
    if config.preferences.get("browser_id") == record.id:
        return
    config.preferences["browser_id"] = record.id
    try:
        config.save()
    except Exception as e:
        print(f"[WebSession] Failed to persist browser preference: {e}")


def resolve_browser(requested: Optional[str] = None) -> Tuple[Optional[BrowserRecord], Optional[str]]:
    """
    Decide which browser to use for a web action.

    - An explicit request is matched against the discovered catalog (never a
      guessed executable name) and, if uniquely resolved, becomes the new
      default going forward.
    - Otherwise, the last browser the user switched to is reused (revalidated
      against a fresh scan if it's gone missing from the cached catalog).
    - Otherwise, falls back to the OS-configured default browser.

    Returns (record, message). `record` is None if nothing could be safely
    resolved; `message` explains why, for the caller to relay to the user —
    ambiguous/uncertain matches are reported, never silently guessed.
    """
    catalog = discover_browsers()

    if requested:
        selection = select_browser(requested, catalog)
        if selection.outcome == SELECTED:
            set_preferred_browser(selection.record)
            return selection.record, None
        if selection.outcome == AMBIGUOUS:
            names = ", ".join(f"{c.display_name} ({c.channel})" for c in selection.candidates)
            return None, f"Multiple installed browsers match '{requested}': {names}. Please be more specific."
        if selection.outcome == NEEDS_CONFIRMATION:
            names = ", ".join(c.display_name for c in selection.candidates)
            return None, f"Not sure which browser you meant by '{requested}' — closest matches: {names}."
        return None, f"'{requested}' doesn't look like an installed browser."

    preferred_id = get_preferred_browser_id()
    if preferred_id:
        active_catalog = catalog if preferred_id in catalog else discover_browsers(force_refresh=True)
        if preferred_id in active_catalog:
            return active_catalog[preferred_id], None
        # Previously chosen browser is genuinely gone — fall through to OS default.

    default_record = get_os_default_record(catalog)
    if default_record:
        set_preferred_browser(default_record)
        return default_record, None

    return None, "No supported browser could be found on this system."


class BrowserSessionManager:
    """
    Singleton. Connects to a running browser via CDP.

    Usage:
        manager = get_browser_manager()
        page = manager.get_active_page()
        page = manager.new_page(url)

    """
    def __init__(self):
        self._config = get_config().web
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._lock = threading.Lock()
        self._connected = False
        self._active_record: Optional[BrowserRecord] = None

    def _find_or_launch_cdp_url(self, record: BrowserRecord) -> str:
        """Find a running instance of THIS browser with CDP enabled, or launch it.
        Only ever matches/launches the resolved record's own exe — never a
        different browser that happens to be listening on the port."""
        import psutil
        import subprocess
        import time

        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                name = proc.info['name']
                if name and name.lower() == record.exe_name:
                    cmdline = proc.info['cmdline']
                    if cmdline:
                        for arg in cmdline:
                            if arg.startswith('--remote-debugging-port='):
                                port = arg.split('=')[1]
                                return f"http://127.0.0.1:{port}"
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        print(f"[WebSession] No CDP session for '{record.display_name}' found. Launching it in debugging mode...")
        user_data_dir = os.path.abspath("data/browser_profile")
        os.makedirs(user_data_dir, exist_ok=True)
        port = "9222"
        cmd = [
            record.exe_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2.0)  # give it a moment to start CDP
        return f"http://127.0.0.1:{port}"

    def connect(self, requested_browser: Optional[str] = None) -> bool:
        """Connects to the browser via CDP. `requested_browser` is an explicit
        override, e.g. the user said "open this in Firefox"."""
        record, message = resolve_browser(requested_browser)
        if not record:
            print(f"[WebSession] {message}")
            return False

        if not record.cdp_hint:
            print(f"[WebSession] '{record.display_name}' isn't recognized by Mei's current "
                  f"web-automation integration (Chromium-based browsers only) — web_navigate/"
                  f"web_click etc. won't work with it.")
            return False

        if self._connected and self._browser and self._browser.is_connected():
            if self._active_record and self._active_record.id == record.id:
                return True
            # A different browser was requested — drop the old Browser/Context
            # only. Do NOT tear down the Playwright driver here (see
            # _release_browser's docstring) — that used to call disconnect(),
            # which stops the sync-API driver, and re-starting sync_playwright()
            # a second time on the same thread is what caused every browser
            # action to fail with "Sync API inside asyncio loop" after the
            # first switch.
            self._release_browser()

        with self._lock:
            if self._connected and self._browser and self._browser.is_connected():
                return True

            try:
                if self._playwright is None:
                    print("[WebSession] About to call sync_playwright().start() (blocking)")
                    self._playwright = sync_playwright().start()
                cdp_url = self._find_or_launch_cdp_url(record)

                print(f"[WebSession] About to call connect_over_cdp({cdp_url}) (blocking, timeout={self._config.default_timeout_ms}ms)")
                self._browser = self._playwright.chromium.connect_over_cdp(
                    cdp_url,
                    timeout=self._config.default_timeout_ms
                )

                contexts  = self._browser.contexts
                if contexts:
                    self._context = contexts[0]
                else:
                    self._context = self._browser.new_context()

                self._connected = True
                self._active_record = record
                emit(EventType.ACTION_COMPLETED,
                     source="BrowserSessionManager",
                     action= "cdp_connect",
                     data={"cdp_url": cdp_url, "browser": record.display_name})

                print(f"[WebSession] Connected to {record.display_name} at {cdp_url}")
                return True

            except Exception as e:
                self._connected = False
                emit(EventType.ERROR,
                     source="BrowserSessionManager",
                     error= str(e),
                     operation="cdp_connect")
                print(f"[WebSession] Failed to connect: {e}")
                return False

    @property
    def is_connected(self)->bool:
        return (self._connected
                and self._browser is not None
                and self._browser.is_connected())

    @property
    def active_browser(self) -> Optional[BrowserRecord]:
        return self._active_record if self.is_connected else None

    def get_active_page(self)->Optional[Page]:
        """
        Get the current active ( most recent used )
        page/tab.
        Connects if not already connected.
        """
        if not self.connect():
            return None

        pages = self._context.pages
        if not pages:
            return self._context.new_page()

        return pages[-1];

    def new_page(self, url: str = None) -> Optional[Page]:
        """Open a new tab, optionally to a URL."""
        if not self.connect():
            return None

        page = self._context.new_page()
        if url:
            try:
                page.goto(url, 
                          wait_until="domcontentloaded",
                          timeout=self._config.default_timeout_ms)

            except Exception:
                pass

        emit(EventType.TAB_OPENED,
             source="BrowserSessionManager",
             url= url or "above:blank")
        return page

    def get_all_pages(self)->list:
        """Get all open tabs/pages."""
        if not self.is_connected:
            return []

        return self._context.pages

    def close_page(self, page: Page)-> bool:
        """Close a specific tab."""
        try:
            url = page.url
            page.close()
            emit(EventType.TAB_CLOSED,
                 source="BrowserSessionManager",
                 url=url)
        except Exception:
            return False

    def _release_browser(self) -> None:
        """
        Drop the current Browser/Context, but keep the Playwright *driver*
        itself alive. Playwright's sync API can only be started once per OS
        thread for the life of the process — calling sync_playwright().start()
        again on a thread that already hosted one (even after stop()) raises
        "Sync API inside asyncio loop", not a helpful "already started"
        message. Since this manager's connect()/get_active_page()/etc. all run
        on the same long-lived worker thread across many commands, tearing
        the driver down on every browser switch permanently broke Playwright
        for the rest of the process after the *first* switch.
        """
        with self._lock:
            try:
                if self._browser:
                    self._browser.close()
            except Exception:
                pass
            finally:
                self._browser = None
                self._context = None
                self._connected = False
                self._active_record = None

    def disconnect(self)->None:
        """
        Full teardown, including the Playwright driver itself. Only call this
        at actual process/app shutdown — NOT to switch browsers mid-session
        (use _release_browser for that, which connect() already does).
        """
        self._release_browser()
        with self._lock:
            try:
                if self._playwright:
                    self._playwright.stop()
            except Exception:
                pass
            finally:
                self._playwright = None
                print("[WebSession] Disconnected from browser")

_manager: Optional[BrowserSessionManager] = None

def get_browser_manager()-> BrowserSessionManager:
    global _manager
    if _manager is None:
        _manager = BrowserSessionManager()
    return _manager
