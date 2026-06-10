from typing import Dict, Any, Tuple, Optional

from ...core.task import ActionHandler
from ...core.config import ActionResult, VerifyResult, WindowInfo,ElementReference
from ...perception.System.windows import get_window_manager
from ..context import ExecutionContext

from ...perception.System.accessibility import UIAutomationManager, UIElement
from ...perception.Visual.screen import ScreenCapture
from ...perception.Visual.analyzer import get_visual_analyzer, VisualElement
from ...memory.store import get_memory_store


import time
import win32gui
import pyautogui


DEFAULT_WAIT_SECONDS = 1.0
MAX_WAIT_SECONDS = 30.0
DEFAULT_FIND_TIMEOUT = 5.0
FIND_RETRY_INTERVAL = 0.5
DEFULT_TYPE_INTERVAL = 0.02
DEFAULT_CLICK_PAUSE = 0.1
DEFAULT_SCROLL_AMOUNT = 3


def _get_ui_automation()->UIAutomationManager:
    global _ui_automation_manager
    if _ui_automation_manager is None:
        _ui_automation_manager = UIAutomationManager()
    return _ui_automation_manager

def _get_screen_capture()->ScreenCapture:
    global _screen_capture
    if _screen_capture is None:
        _screen_capture = ScreenCapture()
    return _screen_capture



def _resolve_window(params: Dict[str,Any], context: ExecutionContext, require_match: bool = True) ->Tuple[Optional[WindowInfo], Optional[str]]:
    window_manager = get_window_manager()
    hwnd = params.get('hwnd')
    if hwnd is not None:
        window = window_manager.get_window_by_hwnd(int(hwnd))
        if window:
            return (window, None)
        else:
            return ( None, f"Window with hwnd {hwnd} not found")
        
    query  = params.get('query') or params.get('title') or params.get('app_name')
    if query:
        window = window_manager.find_window(str(query))
        if window:
            return (window, None)
        else:
            return ( None, f"Window matching '{query}' not found")
    if require_match:
        return (None, "Missing parameters: 'query' or 'hwnd'")
    if context.current_window:
        if win32gui.IsWindow(context.current_window.hwnd):
            return (context.current_window, None)
    
    foreground = window_manager.get_foreground_window()
    if foreground:
        return (foreground, None)
    
    return ( None, 'No window available')


class FindWindowHandler(ActionHandler):
    @property
    def action_name(self) -> str:
        return 'find_window'
    
    @property
    def supports_verification(self) -> bool:
        return True
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        has_query = 'query' in params or 'title' in params
        has_hwnd = 'hwnd' in params
        if not has_query and not has_hwnd:
            return (False, "Missing required parameter: 'query', 'title', or 'hwnd'")
        query = params.get('query') or params.get('title')
        if query is not None and str(query).strip() == "":
            return (False, "Search query cannot be empty")
        return (True, None)
    
    def execute(self, params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
        try:
            query = params.get('query') or params.get('title')
            hwnd = params.get('hwnd')
            
            window_manager = get_window_manager()
            
            if hwnd is not None:
                window = window_manager.get_window_by_hwnd(int(hwnd))
                if window:
                    context.set_current_window(window)
                    return ActionResult(
                        success=True,
                        data={'hwnd': window.hwnd, 'title': window.title, 'process': window.process_name},
                        method_used='window_manager'
                    )
                return ActionResult(success=False, error=f"No window with hwnd {hwnd}", method_used='window_manager')
            
            window = window_manager.find_window(str(query))
            if window:
                context.set_current_window(window)
                return ActionResult(
                    success=True,
                    data={'hwnd': window.hwnd, 'title': window.title, 'process': window.process_name},
                    method_used='window_manager'
                )
            
            return ActionResult(
                success=False,
                error=f"Window matching '{query}' not found",
                method_used='window_manager'
            )
        except Exception as e:
            return ActionResult(success=False, error=f"Exception finding window: {str(e)}", method_used='window_manager')
    
    def verify(self, params: Dict[str, Any], context: ExecutionContext, result: ActionResult) -> VerifyResult:
        hwnd = result.data.get('hwnd') if result.data else None
        if hwnd is None:
            return VerifyResult(verified=False, confidence=0.5, reason="No hwnd in result")
        if win32gui.IsWindow(hwnd):
            return VerifyResult(verified=True, confidence=0.95, reason="Window exists")
        return VerifyResult(verified=False, confidence=0.9, reason="Window no longer exists")


class VerifyWindowHandler(ActionHandler):
    @property
    def action_name(self) -> str:
        return 'verify_window'
    
    @property
    def supports_verification(self) -> bool:
        return False
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if 'expected_title' not in params and 'query' not in params and 'title' not in params:
            return (False, "Missing required parameter: 'expected_title', 'query', or 'title'")
        if 'timeout' in params:
            try:
                t = float(params['timeout'])
                if t <= 0:
                    return (False, "Parameter 'timeout' must be positive")
            except (ValueError, TypeError):
                return (False, "Parameter 'timeout' must be a number")
        return (True, None)
    
    def execute(self, params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
        try:
            query = params.get('expected_title') or params.get('query') or params.get('title')
            timeout = float(params.get('timeout', 5))
            
            window_manager = get_window_manager()
            start_time = time.time()
            
            while (time.time() - start_time) < timeout:
                window = window_manager.find_window(str(query))
                if window:
                    context.set_current_window(window)
                    return ActionResult(
                        success=True,
                        data={
                            'hwnd': window.hwnd,
                            'title': window.title,
                            'process': window.process_name,
                            'wait_time': round(time.time() - start_time, 2)
                        },
                        method_used='window_manager'
                    )
                time.sleep(0.5)
            
            return ActionResult(
                success=False,
                error=f"Window '{query}' did not appear within {timeout}s",
                method_used='window_manager'
            )
        except Exception as e:
            return ActionResult(success=False, error=f"Exception verifying window: {str(e)}", method_used='window_manager')


class FocusWindowHandler(ActionHandler):
    @property
    def action_name(self)-> str:
        return 'focus_window'
    
    @property
    def supports_verification(self)->bool:
        return True
    
    def validate(self, params: Dict[str, Any])-> Tuple[bool, Optional[str]]:
        has_query = 'query' in params or 'title' in params or 'app_name' in params
        has_hwnd = 'hwnd' in params
        
        if not has_query and not has_hwnd:
            return (False, "Missing required parameter: 'query', 'title', 'app_name', or 'hwnd'")
        
        if has_query:
            query = params.get('query') or params.get('title') or params.get('app_name')
            if query is not None and str(query).strip() == "":
                return (False, "Search query/title cannot be an empty string")
        
        if has_hwnd:
            try:
                int(params['hwnd'])
            except ( ValueError, TypeError):
                return ( False, "Parameter 'hwnd' must be a valid integer")
        return ( True, None )
    
    def execute(self, params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
        try:
            window, error = _resolve_window(params=params, context= context, require_match= True)
            if window is None:
                return ActionResult(
                    success= False,
                    error = error,
                    method_used= 'window_manager'
                )
            window_manager = get_window_manager()
            success = window_manager.focus_window(window.hwnd)

            if success:
                context.set_current_window(window)
                return ActionResult(
                    success= True,
                    data = {
                        'hwnd': window.hwnd,
                        'title':window.title,
                        'process': window.process_name
                    },
                    method_used='window_manager'
                )
            else:
                return ActionResult(
                    success =False,
                    error = f'Failed to focus window: {window.title}',
                    method_used="window_manager"
                )
        except Exception as e:
            return ActionResult(
                success= False,
                error = f"Exception focusing window: {str(e)}",
                method_used='window_manager'
            )
    def verify(self, params: Dict[str, Any], context: ExecutionContext, result:ActionResult)->VerifyResult:
        hwnd = result.data.get('hwnd') if result.data else None
        if hwnd is None:
            return VerifyResult(
                verified=False,
                confidence=0.9,
                reason="No hwnd in result to verify"
            )
        if result.data.get("already_restored"):
            return VerifyResult(verified=True,
                                confidence=0.95,
                                reason="Window was already in normal state")
        try:
            import win32con
            is_minimized = win32gui.IsIconic(hwnd)
            placement = win32gui.GetWindowPlacement(hwnd)
            is_maximized = (placement[1] == win32con.SW_SHOWMAXIMIZED)

            if not is_minimized and not is_maximized:
                return VerifyResult(
                    verified=True,
                    confidence=0.95,
                    reason="Window confirmed as restored ( normal state )"
                )
            else:
                state = "minimized" if is_minimized else "maximized"
                return VerifyResult(
                    verified=False,
                    confidence=0.90,
                    reason = f"Window is still {state}"
                )
        except Exception as e:
            return VerifyResult(
                verified=False,
                confidence=0.5,
                reason = f"Verification error: {str(e)}"
            )

class MinimizeWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "minimize_window"

    @property
    def supports_verification(self)->bool:
        return True
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
            has_query = 'query' in params or 'title' in params or 'app_name' in params
            has_hwnd = 'hwnd' in params

            if not has_query and not has_hwnd:
                return (False, "Missing required parameter: 'query', 'title', 'app_name', or 'hwnd'")
            
            if has_query:
                query = params.get('query') or params.get('title') or params.get('app_name')
                if query is not None and str(query).strip() == "":
                    return (False, "Search query/title cannot be an empty string")
            
            if has_hwnd:
                try:
                    int(params['hwnd'])
                except (ValueError, TypeError):
                    return (False, "Parameter 'hwnd' must be a valid integer")
                    
            return (True, None)    
    def execute(self, params:Dict[str,Any], context:ExecutionContext)->ActionResult:
        try:
            window,error = _resolve_window(params, context,require_match=False)
            if window is None:
                return ActionResult(
                    success=False,
                    error=error if error is not None else "No window to minimize",
                    method_used="window_manager"
                )
            if window.is_minimized:
                return ActionResult(
                    success=True,
                    data={
                        'hwnd':window.hwnd,
                        'title':window.title,
                        'already_minimized':True
                    },
                    method_used="window_manager"
                )
            window_manager = get_window_manager()
            success = window_manager.minimize_window(window.hwnd)
            if success:
                if context.current_window and context.current_window.hwnd ==window.hwnd:
                    context.set_current_window(None)

                return ActionResult(
                    success=True,
                    data={
                        'hwnd':window.hwnd,
                        'title': window.title
                    },
                    method_used="window_manager"
                )
            else:
                return ActionResult(
                    success=False,
                    error = f"Failed to minimize window: {window.title}",
                    method_used="window_manager"
                )
        except Exception as e:
            return ActionResult(
                success= False,
                error = f"Exception minimized window: {str(e)}",
                method_used="window_manager"
            )

    def verify(self, params:Dict[str, Any], context: ExecutionContext, result: ActionResult)->VerifyResult:
        hwnd = result.data.get('hwnd') if result.data else None
        if hwnd is None:
            return VerifyResult(
                verified=False,
                confidence=0.9,
                reason="No hwnd in reault to verify"
            )
        if result.data.get('already_minimized'):
            return VerifyResult(
                verified=True,
                confidence=0.95,
                reason="Window was already Minimized"
            )
        try:
            is_minimized = win32gui.IsIconic(hwnd)
            if is_minimized:
                return VerifyResult(
                    verified=True,
                    confidence= 0.95,
                    reason = "Window confirmed as minimized"
                )
            else:
                return VerifyResult(
                    verified=False,
                    confidence=0.9,
                    reason="Window is not minimized"
                )
        except Exception as e:
            return VerifyResult(
                verified=False,
                confidence=0.95,
                reason=f"Verification error: {str(e)}"
            )

class MaximizeWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "maximize_window"
    
    @property
    def supports_verification(self)->bool:
        return True
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        has_query = 'query' in params or 'title' in params or 'app_name' in params
        has_hwnd = 'hwnd' in params

        if not has_query and not has_hwnd:
            return (False, "Missing required parameter: 'query', 'title', 'app_name', or 'hwnd'")
        
        if has_query:
            query = params.get('query') or params.get('title') or params.get('app_name')
            if query is not None and str(query).strip() == "":
                return (False, "Search query/title cannot be an empty string")
        
        if has_hwnd:
            try:
                int(params['hwnd'])
            except (ValueError, TypeError):
                return (False, "Parameter 'hwnd' must be a valid integer")
                
        return (True, None)
    
    def execute(self, params:Dict[str,Any], context:ExecutionContext)->ActionResult:
        try:
            window, error = _resolve_window(params, context, require_match=False)
            if window is None:
                return ActionResult(
                    success=False,
                    error=error if error is not None else "No window to maximize",
                    method_used="window_manager"
                )
            if window.is_maximized:
                context.set_current_window(window)
                return ActionResult(
                    success=True,
                    data={
                        'hwnd':window.hwnd,
                        'title':window.title,
                        'already_maximized': True
                    },
                    method_used="window_manager"
                )
            window_manager = get_window_manager()
            success = window_manager.maximize_window(window.hwnd)
            if success:
                context.set_current_window(window)
                return ActionResult(
                    success =True,
                    data={
                        'hwnd':window.hwnd,
                        'title':window.title
                    },
                    method_used="window_manager"
                )
            else:
                return ActionResult(
                    success=False,
                    error=f"Failed to maximize window: {window.title}",
                    method_used="window_manager"
                )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception maximizing window: {str(e)}",
                method_used="window_manager"
            )
        
    def verify(self, params:Dict[str,Any], context:ExecutionContext, result: ActionResult)->VerifyResult:
        hwnd = result.data.get("hwnd") if result.data else None
        if hwnd is None:
            return VerifyResult(
                verified=False,
                confidence=0.9,                                            
                reason="No hwnd in result to verify"
            )
        if result.data.get("already_maximized"):
            return VerifyResult(
                verified=True,
                confidence=0.95,
                reason="Window was already maximized"
            )
        try:
            import win32con
            placement = win32gui.GetWindowPlacement(hwnd)
            is_maximized = (placement[1] == win32con.SW_SHOWMAXIMIZED)
            if is_maximized:
                return VerifyResult(
                    verified=True,
                    confidence=0.95,
                    reason="Window confirmed as maximized"
                )
            else:                                                          
                return VerifyResult(
                    verified=False,
                    confidence=0.90,
                    reason="Window is not maximized"
                )
        except Exception as e:
            return VerifyResult(
                verified=False,
                confidence=0.5,
                reason=f"Verification error: {str(e)}"
            )
    
class RestoreWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "restore_window"
    
    @property
    def supports_verification(self)->bool:
        return True
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        has_query = 'query' in params or 'title' in params or 'app_name' in params
        has_hwnd = 'hwnd' in params

        if not has_query and not has_hwnd:
            return (False, "Missing required parameter: 'query', 'title', 'app_name', or 'hwnd'")
        
        if has_query:
            query = params.get('query') or params.get('title') or params.get('app_name')
            if query is not None and str(query).strip() == "":
                return (False, "Search query/title cannot be an empty string")
        
        if has_hwnd:
            try:
                int(params['hwnd'])
            except (ValueError, TypeError):
                return (False, "Parameter 'hwnd' must be a valid integer")
                
        return (True, None)
    
    def execute(self, params:Dict[str, Any], context:ExecutionContext)->ActionResult:
        try:
            window, error = _resolve_window(params, context, require_match=False)
            if window is None:
                return ActionResult(
                    success=False,
                    error=error or "No window to restore",
                    method_used="window_manager"
                )
            if not window.is_minimized and not window.is_maximized:
                context.set_current_window(window)
                return ActionResult(
                    success=True,
                    data={
                        'hwnd': window.hwnd,
                        'title': window.title,
                        'already_restored':True
                    },
                    method_used= "window_manager"
                )
            window_manager = get_window_manager()
            success = window_manager.restore_window(window.hwnd)
            if success:
                context.set_current_window(window)
                return ActionResult(
                    success=True,
                    data= {
                        'hwnd':window.hwnd,
                        'title':window.title,
                    },
                    method_used="window_manager"
                )
            else:
                return ActionResult(
                    success= False,
                    error=f"Failed to restore window: {window.title}",
                    method_used='window_manager'
                )
        except Exception as e:
            return ActionResult(
                success=False,
                error= f"Exeption restoring window: {str(e)}",
                method_used="window_manager"
            ) 
    def verify(self, params:Dict[str,Any], context:ExecutionContext, result: ActionResult)->VerifyResult:
        hwnd = result.data.get("hwnd") if result.data else None
        if hwnd is None:
            return VerifyResult(
                verified=False,
                confidence=0.9,                                            
                reason="No hwnd in result to verify"
            )
        if result.data.get("already_restored"):
            return VerifyResult(
                verified=True,
                confidence=0.95,
                reason="Window was already in normal state"
            )
        try:
            import win32con

            is_minimized = win32gui.IsIconic(hwnd)

            placement = win32gui.GetWindowPlacement(hwnd)
            is_maximized = (placement[1] == win32con.SW_SHOWMAXIMIZED)
            if not is_minimized and not is_maximized:
                return VerifyResult(
                    verified=True,
                    confidence=0.95,
                    reason="Window confirmed as restored"
                )
            else:  
                state = "minimized" if is_minimized else 'maximized'                                                        
                return VerifyResult(
                    verified=False,
                    confidence=0.90,
                    reason=f"Window is still {state}"
                )
        except Exception as e:
            return VerifyResult(
                verified=False,
                confidence=0.5,
                reason=f"Verification error: {str(e)}"
            )    
        
class CloseWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "close_window"
    
    @property
    def supports_verification(self)->bool:
        return True
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        has_query = 'query' in params or 'title' in params or 'app_name' in params
        has_hwnd = 'hwnd' in params

        if not has_query and not has_hwnd:
            return (False, "Missing required parameter: 'query', 'title', 'app_name', or 'hwnd'")
        
        if has_query:
            query = params.get('query') or params.get('title') or params.get('app_name')
            if query is not None and str(query).strip() == "":
                return (False, "Search query/title cannot be an empty string")
        
        if has_hwnd:
            try:
                int(params['hwnd'])
            except (ValueError, TypeError):
                return (False, "Parameter 'hwnd' must be a valid integer")
                
        return (True, None)
    
    def execute(self, params: Dict[str, Any], context: ExecutionContext)->ActionResult:
        try:
            window, error = _resolve_window(params=params, context=context, require_match=False)
            if window is None:
                return ActionResult(
                    success = False,
                    error= error or "No window to close",
                    method_used="window_manager"
                )
            hwnd = window.hwnd
            title = window.title
            window_manager = get_window_manager()
            success = window_manager.close_window(hwnd)

            if success:
                if context.current_window and context.current_window.hwnd == hwnd:
                    context.set_current_window(None)
                return ActionResult(
                    success = True, 
                    data={
                        'hwnd': hwnd,
                        'title':title,
                        'closed':True
                    },
                    method_used="window_manager"
                )
            else:
                return ActionResult(
                    success=False,
                    error = f"Failed to close window: {title}",
                    method_used="window_manager"
                )
            
        except Exception as e:
            return ActionResult(
                success = False,
                error = f"Exception closing window: {str(e)}",
                method_used="window_manager"
            )
        
    def verify(self, params:Dict[str,Any], context:ExecutionContext, result: ActionResult)->VerifyResult:
        hwnd = result.data.get("hwnd") if result.data else None
        if hwnd is None:
            return VerifyResult(
                verified=False,
                confidence=0.9,
                reason = "No hwnd in result to verify"
            )
        try:
            import time
            time.sleep(0.2)

            window_exists = win32gui.IsWindow(hwnd)

            if not window_exists:
                return VerifyResult(
                    verified=True,
                    confidence=0.95,
                    reason="Window confirmed as closed (no longer exists)"
                )
            else:
                return VerifyResult(
                    verified=False,
                    confidence = 0.85,
                    reason= "Window still exists ( may have unsaved change dialogies )"
                )
            
        except Exception as e:
            return VerifyResult(
                verified = False,
                confidence= 0.5,
                reason = f"Verificationerror: { str(e) }"
            )

"""──Added─────────────────────────────────────────────────────────────────────────────────────────

Following tools are being added for making a single module for GUI
"""
class FindElementHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return 'find_element'
    
    @property
    def supports_verification(self)->bool:
        return True
    
    @property
    def requires_visual_fallback(self)->bool:
        return True
    
    def validate(self, params:Dict[str,Any])-> Tuple[bool, Optional[str]]:
        has_query = 'query' in params or 'element_name' in params
        if not has_query:
            return (False, "Missing required parameter: 'query' or 'element_name'")
        
        query = params.get('query') or params.get('element_name')
        if query is None or str(query).strip() == "":
            return (False, "Parameter 'query' cannot be empty")
        
        if 'timeout' in params:
            try:
                timeout = float(params['timeout'])
                if timeout <=0:
                    return (False, "Parameter 'timeout' must be positive")
            
            except ( ValueError, TypeError):
                return (False, "Parameter 'timeout' must be a number")
            
        return (True, None)
    
    def execute(self, params:Dict[str,Any], context:ExecutionContext)->ActionResult:
        try:
            query = str(params.get('query') or params.get('element_name', '')).strip()
            element_type = params.get('element_type')
            timeout = params.get('timeout', DEFAULT_FIND_TIMEOUT)
            use_visual = params.get('use_visual', True)
            cache_as = params.get('cache_as', query)

            window = context.get_current_window_or_foreground()
            if not window:
                return ActionResult(
                    success = False,
                    error = 'No window context for element search',
                    method_used='none'
                )
            
            start_time = time.time()
            last_error = 'Element not found'
            attempt = 0

            while(time.time()-start_time) < timeout:
                attempt +=1

                result = self._find_via_ui_automation(
                    query,element_type,window.hwnd
                )
                if result:
                    element,ref = result
                    context.store_element(cache_as, ref)
                    return ActionResult(
                        success=True,
                        data = {
                            'element_name': element.name,
                            'element_typ':element.control_type,
                            'bounding_box': element.bounding_box,
                            'cached_as': cache_as,
                            'source':'ui_automation',
                            'attempt':attempt
                        },
                        method_used="ui_automation"
                    )
                
                if use_visual:
                    result = self._find_via_visual(
                        query,element_type, window.hwnd
                    )
                    if result:
                        visual_element,ref = result
                        context.store_element(cache_as,ref)
                        return ActionResult(
                            success=True,
                            data = {
                                'element_label':visual_element.label,
                                'element_type':visual_element.element_type,
                                'bounding_box':visual_element.bounding_box,
                                'center':visual_element.center,
                                'confidence':visual_element.confidence,
                                'cached_as':cache_as,
                                'source':'visual',
                                'attempt':attempt
                            },
                            method_used='visual'
                        )
                time.sleep(FIND_RETRY_INTERVAL)
            
            # Timeout — element not found after all attempts
            return ActionResult(
                success=False,
                error=f"Element '{query}' not found after {attempt} attempts ({timeout}s timeout)",
                method_used='none'
            )

        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception finding element: {str(e)}",
                method_used='none'
            )

        
    def _find_via_ui_automation(self, query:str, element_type:Optional[str], hwnd:int)->Optional[Tuple[UIElement, ElementReference]]:
        try:
            ui_manager = _get_ui_automation()
            element = ui_manager.find_element(
                hwnd, name = query,
                control_type=element_type,
                partial_match=True
            )

            if element:
                ref = ElementReference(
                    source = 'ui_automation',
                    bounding_box=element.bounding_box,
                    ui_element=element
                )
                return (element,ref)
            return None
        
        except:
            return None
        
    def _find_via_visual(self, query:str, element_type:Optional[str], hwnd:int)->Optional[Tuple[VisualElement, ElementReference]]:
        try:
            visual_analyzer = get_visual_analyzer()
            if not visual_analyzer.is_loaded():
                if not visual_analyzer.preload():
                    return None
                
            screen_capture = _get_screen_capture()
            screeenshot= screen_capture.capture_window(hwnd, bring_to_front=False)
            if not screeenshot:
                return None
            
            visual_element = visual_analyzer.find_element(
                screenshot=screeenshot,
                query=query,
                element_type=element_type
            )

            if visual_element:
                ref = ElementReference(
                    source='visual',
                    bounding_box=visual_element.bounding_box,
                    visual_element=visual_element
                )
                return (visual_element, ref)
            
        except:
            return None
    
    def verify(self, params:Dict[str,Any], context: ExecutionContext, result: ActionResult)->VerifyResult:
        if not result.success:
            return VerifyResult(
                verified=False,
                confidence=0.0,
                reason = 'Element was not found'
            )
        
        cache_as = params.get('cache_as', params['query'])
        cached = context.get_element(cache_as)

        if cached and not cached.is_stale():
            confidence = result.data.get('confidence', 1.0)
            return VerifyResult(
                verified=True,
                confidence=float(confidence),
                reason = f"Element cached as '{cache_as}'"
            )
        
        else:
            return VerifyResult(
                verified=False,
                confidence=0.5,
                reason = "Element not in cache or stale"
            )

class TypeTextHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return 'type_text'

    @property
    def supports_verification(self)->bool:
        return False
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if 'text' not in params:
            return (False, "Missing required parameter: 'text'")
        
        text = params['text']
        if text is None:
            return (False, "Parameter 'text' cannot be None")
         
        if 'interval' in params:
            try:
                interval = float(params['interval'])
                if interval<0:
                    return (False, "Parameter 'interval' must be non-negative")
            except (ValueError, TypeError):
                return (False, "Parameter 'interval' must be a number")
        return (True, None)
    
    def execute(self, params:Dict[str, Any], context: ExecutionContext)->ActionResult:
        try:
            text = str(params['text'])
            element_query = params.get("element_query")
            clear_first = params.get("clear_first", False)
            interval = params.get("interval", DEFULT_TYPE_INTERVAL)
            use_clipboard = params.get("use_clipboard", False)

            context.set_variable("typed_text", text)

            if element_query:
                result = self._type_into_element(
                    text, element_query, context, clear_first, interval
                )
                if result.success:
                    return result
                
            window = context.get_current_window_or_foreground()
            if not window:
                return ActionResult(
                    success=False,
                    error="No window available to type into",
                    method_used='none'
                )
            
            if clear_first:
                pyautogui.hotkey('ctrl','a')
                time.sleep(0.05)
                pyautogui.press('delete')
                time.sleep(0.05)

            if use_clipboard:
                self._type_via_clipboard(text)
                method='clipboard'
            else:
                pyautogui.write(text, interval=interval)
                method='pyautogui'
            
            return ActionResult(
                success=True,
                data={
                    'text_length':len(text),
                    'text_preview':text[:50] if len(text) > 50 else text,
                    'clear_first':clear_first
                },
                method_used=method
            )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception typing text: {str(e)}",
                method_used='pyautogui'
            )
        
    def _type_into_element(self, text:str, element_query:str,
                           context:ExecutionContext,
                           clear_first:bool,
                           interval:float)->ActionResult:
        window = context.get_current_window_or_foreground()
        if not window:
            return ActionResult(
                success=False,
                error= "No window context for element search",
                method_used='ui_automation'
            )

        cached_ref = context.get_element(element_query)
        if cached_ref and cached_ref.ui_element:
            element = cached_ref.ui_element
        
        else:
            ui_manager = _get_ui_automation()
            element = ui_manager.find_element(
                window.hwnd,
                name=element_query,
                partial_match=True
            )
        
        if not element:
            return ActionResult(
                success=False,
                error = f"Element '{element_query}' not found",
                method_used="ui_automation"
            )
        
        if not cached_ref:
            ref = ElementReference(
                source="ui_automation",
                bounding_box=element.bounding_box,
                ui_element=element
            )
            context.store_element(element_query, ref)
        
        ui_manager = _get_ui_automation()
        success = ui_manager.type_text(element=element, text=text, clear_first=clear_first)

        if success:
            return ActionResult(
                success=True,
                data= {
                    'text_length': len(text),
                    'element_name':element.name,
                    'element_type':element.control_type
                },
                method_used="ui_automation"
            )
        
        else:
            return ActionResult(
                success=False,
                error=f"Failed to type into element '{element_query}'",
                method_used='ui_automation'
            )
        
    def _type_via_clipboard(self, text:str)->None:
        import pyperclip

        try:
            old_clipboard = pyperclip.paste()
        except:
            old_clipboard = ""
        
        pyautogui.hotkey('ctrl','v')
        time.sleep(0.05)

        try:
            pyperclip.copy(old_clipboard)
        except:
            pass

class HotkeyHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return 'hotkey'
    
    @property
    def supports_verification(self)->bool:
        return False
    
    def validate(self, params:Dict[str, Any])->Tuple[bool, Optional[str]]:
        if 'keys' not in params:
            return ( False, "Missing required parameter: 'keys'")
        
        keys = params['keys']
        
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split('+') if k.strip()]
            params['keys'] = keys 
        
        if not isinstance(keys, (list, tuple)):
            return (False, "Parameter 'keys' must be a list or string like 'ctrl+c'")
        
        if len(keys) == 0:
            return (False, "Parameter 'keys' cannot be empty")
        
        for i,key in enumerate(keys):
            if not isinstance(key,str):
                return (False, f"key at index {i} must be a string")
            if key.strip() == "":
                return (False, f"Key at index {i} cannot be empty")
            
        return (True, None)
    
    def execute(self, params:Dict[str, Any], context: ExecutionContext)->ActionResult:
        try:
            keys = [str(k).lower().strip() for k in params['keys']]
            hold_time = params.get('hold_time',0)

            dangerous_combos = [
                ["alt", 'f4'],
                ['ctrl;','w'],
                ['ctrl', 'shift','delete']
            ]
            keys_set = set(keys)
            for combo in dangerous_combos:
                if set(combo) == keys_set:
                    print(f"Executing potentially destrictive hotkey: {keys}")
                break

            context.set_variable("last_hotkey", keys)

            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys, interval=0.05)
            
            if hold_time >0:
                time.sleep(hold_time)

            return ActionResult(
                success=True,
                data={
                    'keys':keys,
                    'key_count': len(keys)
                }, 
                method_used="pyautogui"
            )
        
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception pressing hotkey: {str(e)}",
                method_used='pyautogui'
            )
    
class ClickHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return 'click'
    
    @property
    def supports_verification(self)->bool:
        return False
    
    @property
    def requires_visual_fallback(self)->bool:
        return True
    
    def validate(self, params:Dict[str,Any])->Tuple[bool, Optional[str]]:
        has_query = 'query' in params or 'element_name' in params
        has_coords = 'x' in params and 'y' in params

        if not has_query and not has_coords:
            return (False, "Missing required parameter: 'query', 'element_name', or 'x,y' coordinates")
        
        if has_query:
            query = params.get('query') or params.get('element_name')
            if query is None or str(query).strip() == "":
                return (False, "Parameter 'query' cannot be empty")
        
        if has_coords:
            try:
                x = int(params['x'])
                y = int(params['y'])
                if x<0 and y <0:
                    return (False, "Coordinates cannot be negative")
            
            except ( ValueError, TypeError):
                return (False, "Parameter 'x' and 'y' must be integers")
            
        if 'click_type' in params:
            click_type = params['click_type']
            valid_types = ['left', 'right', 'double']
            if click_type not in valid_types:
                return (False, f"click_type must be one of: {valid_types}")
        
        return (True, None)
    
    def execute(self, params: Dict[str, Any], context: ExecutionContext)->ActionResult:
        try:
            query = params.get('query') or params.get('element_name')
            x = params.get('x')
            y = params.get('y')
            click_type = params.get('click_type','left')
            use_visual_fallback = params.get('use_visual_fallback', True)
            element_type = params.get('element_type')

            if x is not None and y is not None:
                return self._click_at_coords(int(x),int(y),click_type)
            
            query = str(query).strip()


            store = get_memory_store()
            app_name = "unknown"
            window_pattern = None
            

            if context.current_window:
                app_name = context.current_window.process_name or "unknown"
                window_pattern = self._simplify_window_title(context.current_window)
            cached_pos = store.get_cached_element(
                element_query=query, 
                app_name=app_name, 
                window_pattern=window_pattern
            )
            
            if cached_pos:
                ref = ElementReference(
                    source="cached_persistent",
                    bounding_box=(
                        cached_pos['bounding_box_x'], cached_pos['bounding_box_y'],
                        cached_pos['bounding_box_w'], cached_pos['bounding_box_h']
                    ),
                    ui_element=None
                )
                result = self._click_cached_element(ref, query, click_type)
                result.data['used_cached_position'] = True
                return result
        
                            
            cached_ref = context.get_element(query)
            if cached_ref:
                return self._click_cached_element(cached_ref, query, click_type)
            
            result = self._click_via_ui_automation(query,element_type,context,click_type)
            if result.success:
                return result
            
            if use_visual_fallback:
                result = self._click_via_visual(query,element_type,context, click_type)

                if result.success:
                    return result
            
            return ActionResult(
                success = False,
                error = f"Element '{query} not found via UI Automation or Visual Detection if use_visual_fallback else ''",
                method_used='none'
            )
    
        except Exception as e:
            return ActionResult(
                success=False,
                error = f"Exception during click: {str(e)}",
                method_used='none'
            )
        
    def _simplify_window_title(self,title:str)->str:
        if not title:
            return '%'
        
        if " - " in title:
            parts = title.split(" - ")

            app_part = parts[-1].strip()

            if len(app_part) > 2:
                return f"%{app_part}%"
            
        if len(title) < 20:
            return f"%{title}%"
        
        return f"%{title[:20]}%"
    
    def _click_at_coords(self,x:int, y:int, click_type:str)->ActionResult:
        if click_type=='left':
            pyautogui.click(x,y)
        
        elif click_type == 'right':
            pyautogui.rightClick(x,y)
        
        elif click_type == 'double':
            pyautogui.doubleClick(x,y)

        time.sleep(DEFAULT_CLICK_PAUSE)

        return ActionResult(
            success=True,
            data={
                'x':x,
                'y':y,
                'click_type':click_type
            },
            method_used="pyautogui"
        )
    
    def _click_cached_element(self, cached_ref:ElementReference, query:str, click_type:str)->ActionResult:
        bbox = cached_ref.bounding_box
        center_x = bbox[0] + bbox[2]//2
        center_y = bbox[1] + bbox[3] //2

        result = self._click_at_coords(center_x,center_y, click_type)

        if result.success:  
            result.data['source'] = 'cached'
            result.data['element_query'] = query
            result.method_used = f"cached_{cached_ref.source}"
        
        return result
    
    def _click_via_ui_automation(self, query:str, element_type:Optional[str], context: ExecutionContext, click_type:str)->ActionResult:
        window = context.get_current_window_or_foreground()
        if not window:
            return ActionResult(
                success=False,
                error = "No window context for UI Automation search",
                method_used='ui_automaiton'
            )
        
        ui_manager = _get_ui_automation()
        element = ui_manager.find_element(
            window.hwnd,
            name = query,
            control_type=element_type,
            partial_match=True
        )
        
        if not element:
            return ActionResult(
                success = False,
                error = f"Element '{query}' not found via UI Automation",
                method_used="ui_automatoin"
            )
        
        ref = ElementReference(
            source='ui_automation',
            bounding_box=element.bounding_box,
            ui_element=element
        )
        context.store_element(query,ref)

        bbox = element.bounding_box
        center_x = bbox[0] + bbox[2] //2
        center_y = bbox[1] + bbox[3] //2

        success = ui_manager.click_element(element, 'left')
        if success:
            return ActionResult(
                success=True,
                data= {
                    'element_name': element.name,
                    'element_type': element.control_type,
                    'x':center_x,
                    'y':center_y,
                    'click_type':click_type
                },
                method_used='ui_automation'
            )
        result =  self._click_at_coords(center_x,center_y, click_type)
        if result.success:
            result.data["element_name"] = element.name
            result.data["element_type"] = element.control_type
            result.data["source"] = "ui_automation"
            result.method_used = "ui_automation_pyautogui"
        return result

    
    def _click_via_visual(self, query:str, element_type:Optional[str], context: ExecutionContext, click_type:str)->ActionResult:
        try:
            visual_analyzer = get_visual_analyzer()

            if not visual_analyzer.is_loaded():
                if not visual_analyzer.preload():
                    return ActionResult(
                        success=False,
                        error="Visual analyzer not available",
                        method_used='visual_fallback'
                    )
            
            screen_capture = _get_screen_capture()
            window = context.get_current_window_or_foreground()
            if window:
                screenshot = screen_capture.capture_window(window.hwnd, bring_to_front=True)   
            else: 
                screenshot = screen_capture.capture_active_window()
            if not screenshot:
                return ActionResult(
                    success=False,
                    error = "Failed to capture screenshot for visual search",
                    method_used="visual_fallback"
                )

            visual_element = visual_analyzer.find_element(
                screenshot,
                query,
                element_type=element_type
            )
            if not visual_element:
                return ActionResult(
                    success=False,
                    error = f"Element '{query}' not found via visual detection",
                    method_used="visual_fallback"
                )
            
            ref = ElementReference(
                source="visual",
                bounding_box=visual_element.bounding_box,
                visual_element=visual_element
            )
            context.store_element(query,ref)
            center_x,center_y = visual_element.center

            result = self._click_at_coords(center_x,center_y, click_type)

            if result.success:
                result.data['source'] = 'visual'
                result.data["element_label"] = visual_element.label
                result.data["element_type"] = visual_element.element_type
                result.data["confidence"] = visual_element.confidence
                result.method_used = "visual_fallback"
            return result
        
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Visual fallback error: {str(e)}",
                method_used="visual_fallback"
            )

class ScrollHander(ActionHandler):
    @property
    def action_name(self) -> str:
        return "scroll"
    
    @property
    def supports_verification(self) -> bool:
        return False
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if "direction" not in params:
            return (False, 
            "Missing required parameter: 'direction'")
        
        direction = params["direction"]
        if direction not in ["up", "down"]:
            return (False, "Parameter 'direction' must be 'up' or 'down'")
        
        if "amount" in params:
            try:
                amount = int(params["amount"])
                if amount <= 0:
                    return (False, "Parameter 'amount' must be positive")
                
            except (ValueError, TypeError):
                return (False, "Parameter 'amount' must be an integer")
        
        if "x" in params or "y" in params:
            if "x" not in params or "y" not in params:
                return (False, "Both 'x' and 'y' must be provided together")

            try:
                int(params["x"])
                int(params["y"])
            except (ValueError, TypeError):
                return (False, "Parameters 'x' and 'y' must be integers")
        
        return (True, None)
     
    def execute(self, params: Dict[str, Any], context: ExecutionContext)->ActionResult:
        try:
            direction = params['direction']
            amount = params.get('amount', DEFAULT_SCROLL_AMOUNT)
            x = params.get('x')
            y = params.get('y')
            
            scroll_amount = int(amount) if direction == 'up' else -int(amount)

            if x is not None and y is not None:
                pyautogui.moveTo(int(x), int(y))
                time.sleep(0.05)
            
            pyautogui.scroll(scroll_amount)

            return ActionResult(
                success=True,
                data={
                    'direction':direction,
                    'amount':amount,
                    'scroll_value':scroll_amount,
                    'x':x,
                    'y':y
                },
                method_used='pyautogui'
            )
        
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception during scroll: {str(e)}",
                method_used='pyautogui'
            )
        


WINDOW_HANDLERS = [
    FindWindowHandler,
    VerifyWindowHandler,
    FocusWindowHandler,
    MinimizeWindowHandler,
    MaximizeWindowHandler,
    RestoreWindowHandler,
    CloseWindowHandler,
    FindElementHandler,
    TypeTextHandler,
    HotkeyHandler,
    ClickHandler,
    ScrollHander
]

def get_window_handlers()->list:
    return [handler_class() for handler_class in WINDOW_HANDLERS]
    
    

if __name__ == "__main__":                                   
    import time                                              
    from ...core.task import Plan, Intent, Step, StepStatus 
    from ...action.context import ExecutionContext          
                                                             
    time.sleep(2)                                            
                                                             
    dummy_intent = Intent(                                   
        action="test",                                       
        target="windows",                                    
        raw_command="testing window handlers"                
    )                                                        
    dummy_plan = Plan(steps=[], strategy="test")             
    context = ExecutionContext(dummy_plan, dummy_intent)     
                                                             
    print("\nTEST 1: FocusWindowHandler")                    
    print("-" * 40)                                          
                                                             
    focus_handler = FocusWindowHandler()                     
    print(f"  action_name: {focus_handler.action_name}")     
    print(f"  supports_verification: {focus_handler.supports_verification}")
                                                             
    # Test validation - missing params                       
    is_valid, error = focus_handler.validate({})             
    print(f"  validate({{}}): valid={is_valid}, error={error}")    
    assert not is_valid, "Should fail with empty params"     
                                                             
    # Test validation - valid params                         
    is_valid, error = focus_handler.validate({"query": "Code"}) 
    print(f"  validate({{query:'Code'}}): valid={is_valid}")    
    assert is_valid, "Should pass with query"                
                                                             
    # Test execution                                         
    result = focus_handler.execute({"query": "Code"}, context)  
    print(f"  execute result: success={result.success}")     
    if result.success:                                       
        print(f"    hwnd: {result.data.get('hwnd')}")        
        print(f"    title: {result.data.get('title')}")      
        print(f"    context.current_window set: {context.current_window is not None}")
                                                             
        # Test verification                                  
        verify = focus_handler.verify({"query": "Code"}, context, result)
        print(f"  verify: verified={verify.verified}, confidence={verify.confidence}")
        print(f"    reason: {verify.reason}")                
    else:                                                    
        print(f"    error: {result.error}")                  
                                                             
    time.sleep(1)                                            
                                                            
    print("\nTEST 2: MinimizeWindowHandler")                 
    print("-" * 40)                                          
                                                             
    minimize_handler = MinimizeWindowHandler()               
                                                             
    # First focus notepad                                    
    focus_handler.execute({"query": "VSCODE"}, context)     
    time.sleep(0.5)                                          
                                                             
    # Test minimize with empty params (uses current window)  
    is_valid, error = minimize_handler.validate({})          
    print(f"  validate({{}}): valid={is_valid} (empty params OK)") 
                                                             
    result = minimize_handler.execute({}, context)           
    print(f"  execute (current window): success={result.success}") 
    if result.success:                                       
        print(f"    minimized: {result.data.get('title')}")  
        print(f"    context.current_window cleared: {context.current_window is None}")
                                                             
        verify = minimize_handler.verify({}, context, result)
        print(f"  verify: verified={verify.verified}")       
    else:                                                    
        print(f"    error: {result.error}")                  
                                                             
    time.sleep(1)                                            
                                                             
    print("\nTEST 3: RestoreWindowHandler")                  
    print("-" * 40)                                          
                                                             
    restore_handler = RestoreWindowHandler()                 
                                                             
    # Restore the minimized notepad                          
    result = restore_handler.execute({"query": "brave"}, context)
    print(f"  execute: success={result.success}")            
    if result.success:                                       
        print(f"    restored: {result.data.get('title')}")   
        print(f"    context.current_window set: {context.current_window is not None}")
                                                             
        verify = restore_handler.verify({"query": "brave"}, context, result)
        print(f"  verify: verified={verify.verified}")       
    else:                                                    
        print(f"    error: {result.error}")                  
                                                             
    time.sleep(1)                                            
                                                             
    print("\nTEST 4: MaximizeWindowHandler")                 
    print("-" * 40)                                          
                                                             
    maximize_handler = MaximizeWindowHandler()               
                                                             
    # Maximize calculator                                    
    result = maximize_handler.execute({"query": "calculator"}, context)
    print(f"  execute: success={result.success}")            
    if result.success:                                       
        print(f"    maximized: {result.data.get('title')}")  
                                                             
        verify = maximize_handler.verify({"query": "calculator"}, context, result)
        print(f"  verify: verified={verify.verified}")       
    else:                                                    
        print(f"    error: {result.error}")                  
                                                             
    time.sleep(1)                                            
                                                             
    # Restore calculator                                     
    restore_handler.execute({"query": "calculator"}, context)
                                                             
    print("\nTEST 5: CloseWindowHandler")                    
    print("-" * 40)                                          
    print("  Skipping close test to preserve your windows")  
    print("  To test manually:")                             
    print("    close_handler = CloseWindowHandler()")        
    print("    result = close_handler.execute({'query': 'notepad'}, context)")
                                                             
    close_handler = CloseWindowHandler()                     
    is_valid, error = close_handler.validate({"query": "notepad"}) 
    print(f"  validate: valid={is_valid}")                   
                                                             
    # ─────────────────────────────────────────────────────────────────   
    # TEST 6: Error cases                                    
    # ─────────────────────────────────────────────────────────────────   
    print("\nTEST 6: Error Cases")                           
    print("-" * 40)                                          
                                                             
    # Non-existent window                                    
    result = focus_handler.execute({"query": "nonexistent_window_xyz"}, context)
    print(f"  focus non-existent: success={result.success}") 
    print(f"    error: {result.error}")                      
                                                             
    # Invalid hwnd type                                      
    is_valid, error = focus_handler.validate({"hwnd": "not_a_number"})   
    print(f"  validate invalid hwnd: valid={is_valid}")      
    print(f"    error: {error}")                             
                                                             
    # Empty query                                            
    is_valid, error = focus_handler.validate({"query": ""})  
    print(f"  validate empty query: valid={is_valid}")       
    print(f"    error: {error}")                             
                                                             
    print("\nTEST 7: Handler Registration")                  
    print("-" * 40)                                          
                                                             
    handlers = get_window_handlers()                         
    print(f"  Total window handlers: {len(handlers)}")       
    for h in handlers:                                       
        print(f"    - {h.action_name} (verify: {h.supports_verification})")
                                                             
    print("\n" + "=" * 60)                                   
    print("WINDOW HANDLERS TEST COMPLETE")                   
    print("=" * 60)                                          
                                                             
