import time
import webbrowser
from typing import Dict, Optional, Any,Tuple, Optional

from ...core.task import ActionHandler
from ...core.config import ActionResult, VerifyResult

from ...perception.System.windows import get_window_manager

import pyautogui

from ..context import ExecutionContext

BROWSER_PROCESSES = ["chrome.exe","brave.exe","vivaldi.exe"]

URL_PREFIXES = ["http://", "https://", "www.","file://"]

COMMON_DOMAINS = [".com", ".org", ".net", ".io", ".gov", ".edu"]

ADDRESS_BAR_WAIT = 0.2

NAVIGATION_WAIT = 2.0

class NavigateUrlHander(ActionHandler):
    @property
    def action_name(self) -> str:
        return "navigate_url"
    
    @property
    def supports_verification(self)->bool:
        return False
    
    def validate(self, params:Dict[str,Any])-> Tuple[bool, Optional[str]]:
        if 'url' not in params:
            return (False, "Missing required parameter: 'url'")
        
        url = params['url']
        if url is None or str(url).strip() == "":
            return (False, "parameter 'url' cannot be empty")
        
        return (True, None)
    
    def execute(self, params:Dict[str,Any], context:ExecutionContext)->ActionResult:
        try:
            url = str(params['url']).strip()
            new_tab = params.get('new_tab', False)
            use_existing_browser = params.get('use_existing_browser',True)

            normalized_url = self._normalized_url(url)
            context.set_variable('navigate_url', normalized_url)
            
            if self._is_file_path(url):
                return self._open_file_path(url)
            
            if use_existing_browser:
                result = self._navigate_in_browser(
                    normalized_url,new_tab,context
                )
                if result.success:
                    return result
        
            return self._open_in_default_browser(normalized_url)
        
        except Exception as e:
            return ActionResult(
                success=False,
                error =f"Exception during navigation: {str(e)}",
                method_used="none"
            )
    
    def _normalized_url(self,url:str)->str:
        url = url.strip()
        if any(url.lower().startswith(p) for p in URL_PREFIXES):
            if url.lower().startswith("www."):
                return 'https://'+url
            return url
        
        if any(tld in url.lower() for tld in COMMON_DOMAINS):
            return 'https://' + url
        
        if " " in url:
            return url
        
        return 'https://' + url
    
    def _is_file_path(self,url:str)->bool:
        import os

        if len(url) >=2 and url[1] == ':':
            return True
        if url.startswith("\\\\"):
            return True
        if url.startswith("file://"):
            return True
        if os.path.exists(url):
            return True
        
        return False
    
    def _open_file_path(self,path:str)->ActionResult:
        import os
        import subprocess
        try:
            if path.startswith('file://'):
                path = path[7:]
            
            os.startfile(path)
            return ActionResult(
                success = True,
                data={
                    'path':path,
                    'type':'file_path'
                },
                method_used="os_startfile"
            )
        
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Failed to open path: {str(e)}",
                method_used="os_startfile"
            )
        
    def _navigate_in_browser(self,url:str,new_tab:bool,context:ExecutionContext)->ActionResult:
        window_manager = get_window_manager()

        current_window = context.current_window
        browser_window = None

        if current_window:
            if self._is_browser(current_window.process_name):
                browser_window = current_window

        if not browser_window:
            all_windows = window_manager.get_all_windows()
            for win in all_windows:
                if self._is_browser(win.process_name):
                    browser_window=win
                    break
        
        if not browser_window:
            return ActionResult(
                success=False,
                error = "No browser window found",
                method_used="browser_navigation"
            )
        
        window_manager.focus_window(browser_window.hwnd)
        context.set_current_window(browser_window)
        time.sleep(0.1)

        if new_tab:
            pyautogui.hotkey('ctrl','t')
            time.sleep(0.2)

        pyautogui.hotkey('ctrl','l')
        time.sleep(ADDRESS_BAR_WAIT)

        pyautogui.write(url,interval=0.02)
        time.sleep(0.1)

        pyautogui.press('enter')
        time.sleep(NAVIGATION_WAIT)

        return ActionResult(
            success=True,
            data={
                'url':url,
                'browser':browser_window.process_name,
                'new_tab': new_tab,
                'window_title':browser_window.title
            },
            method_used="browser_navigation"
        )
    
    def _open_in_default_browser(self, url:str)->ActionResult:
        try:
            webbrowser.open(url)
            return ActionResult(
                success=True,
                data={
                    'url':url,
                    'method':'default_browser'
                },
                method_used='webbrowser'
            )
        
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Failed to open in default browser: {str(e)}",
                method_used='webbrowser'
            )
        
NAVIGATION_HANDLERS = [
    NavigateUrlHander
]
def get_navigation_handlers()->list:
    return [handler() for handler in NAVIGATION_HANDLERS]

__all__ = [
    'NavigateUrlHandler',
    'NAVIGATION_HANDLERS',
    'get_navigation_handlers',
]