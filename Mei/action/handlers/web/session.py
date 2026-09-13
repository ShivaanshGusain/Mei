"""
Singleton manager for a Playwright browser session over CDP

Connects once to an already-running browser at
localhost:9222.
All web tools as this manager for active page.
"""

import threading
from typing import Optional
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright

from ....core.config import get_config
from ....core.events import emit, EventType


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

    def _find_or_launch_cdp_url(self) -> str:
        """Find a running browser with CDP enabled, or launch one."""
        import psutil
        import subprocess
        import time

        # 1. Look for existing running browsers with CDP
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                name = proc.info['name']
                if name and name.lower() in ('chrome.exe', 'msedge.exe', 'brave.exe'):
                    cmdline = proc.info['cmdline']
                    if cmdline:
                        for arg in cmdline:
                            if arg.startswith('--remote-debugging-port='):
                                port = arg.split('=')[1]
                                return f"http://127.0.0.1:{port}"
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        # 2. If not found, try default configured URL anyway
        # (It might be running without psutil being able to read cmdline, or remote)
        # But we don't want to blindly wait for timeout if it's not there.
        # Let's launch one instead if nothing is explicitly configured differently than default.

        # 3. Launch a new browser (Edge is usually available on Windows)
        print("[WebSession] No CDP browser found. Launching Edge in debugging mode...")
        import os
        edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

        exe_to_run = None
        for path in [brave_path, chrome_path, edge_path]:
            if os.path.exists(path):
                exe_to_run = path
                break
        
        if exe_to_run:
            # We must use a separate user data dir so it can run alongside a normal browser instance
            user_data_dir = os.path.abspath("data/browser_profile")
            os.makedirs(user_data_dir, exist_ok=True)
            port = "9222"
            cmd = [
                exe_to_run,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data_dir}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2.0) # give it a moment to start CDP
            return f"http://127.0.0.1:{port}"

        # 4. Fallback to configured
        return self._config.cdp_url

    def connect(self)->bool:
        """Connects to the browser via CDP"""
        if self._connected and self._browser and self._browser.is_connected():
            return True

        with self._lock:
            if self._connected and self._browser and self._browser.is_connected():
                return True

            try:
                self._playwright = sync_playwright().start()
                cdp_url = self._find_or_launch_cdp_url()

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
                emit(EventType.ACTION_COMPLETED,
                     source="BrowserSessionManager",
                     action= "cdp_connect",
                     data={"cdp_url": cdp_url})

                print(f"[WebSession] Connected to browser at {cdp_url}")
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
        return (self.connected 
                and self._browser is not None
                and self._browser.is_connected())

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

    def disconnect(self)->None:
        """Disconnect from the browser ( does not close it )."""
        with self._lock:
            try:
                if self._browser:
                    self._browser.close()
                if self._playwright:
                    self._playwright.stop()
            except Exception:
                pass
            finally:
                self._browser = None
                self._context = None
                self._playwright = None
                self._connected = False
                print("[WebSession] Disconnected from browser")

_manager: Optional[BrowserSessionManager] = None

def get_browser_manager()-> BrowserSessionManager:
    global _manager
    if _manager is None:
        _manager = BrowserSessionManager()
    return _manager
