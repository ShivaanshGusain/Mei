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

    def connect(self)->bool:
        """Connects to the browser via CDP"""
        if self._connected and self._browser and self._browser.is_connected():
            return True

        with self._lock:
            if self._connected and self._browser and self._browser.is_connected():
                return True

        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(
                self._config.cdp_url,
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
                 data={"cdp_url": self._config.cdp_url})

            print(f"[WebSession] Connected to browser at {self._config.cdp_url}")
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
