from typing import Dict, Any, Tuple, Optional

from ...core.task import ActionHandler
from ...core.config import ActionResult, VerifyResult, WindowInfo,ElementReference
from ...perception.System.windows import get_window_manager
from ..context import ExecutionContext

from ...perception.System.accessibility import UIAutomationManager, UIElement
from ...perception.Visual.screen import ScreenCapture
from ...perception.Visual.analyzer import get_visual_analyzer, VisualElement
from ...memory.store import get_memory_store
from ..executor import PlanExecutor

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




"""Helper functions"""
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
        
    query  = params.get('query') or params.get('title')
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

"""
class FindWindowHandler(ActionHandler):
    @property
    def action_name(self) -> str:
        return 'find_window'
    
    @property
    def supports_verification(self) -> bool:
        return True
"""

def find_window_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    has_query = 'query' in params or 'title' in params
    has_hwnd = 'hwnd' in params
    if not has_query and not has_hwnd:
        return (False, "Missing required parameter: 'query', 'title', or 'hwnd'")
    query = params.get('query') or params.get('title')
    if query is not None and str(query).strip() == "":
        return (False, "Search query cannot be empty")
    return (True, None)

def find_window_execute(params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
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

def find_window_verify(params: Dict[str, Any], context: ExecutionContext, result: ActionResult) -> VerifyResult:
    hwnd = result.data.get('hwnd') if result.data else None
    if hwnd is None:
        return VerifyResult(verified=False, confidence=0.5, reason="No hwnd in result")
    if win32gui.IsWindow(hwnd):
        return VerifyResult(verified=True, confidence=0.95, reason="Window exists")
    return VerifyResult(verified=False, confidence=0.9, reason="Window no longer exists")

"""
class VerifyWindowHandler(ActionHandler):
    @property
    def action_name(self) -> str:
        return 'verify_window'
    
    @property
    def supports_verification(self) -> bool:
        return False
"""

# Does not support verification
def verify_window_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
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

def verify_window_execute(params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
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

"""
class FocusWindowHandler(ActionHandler):
    @property
    def action_name(self)-> str:
        return 'focus_window'
    
    @property
    def supports_verification(self)->bool:
        return True
"""    
def focus_window_validate(params: Dict[str, Any])-> Tuple[bool, Optional[str]]:
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

def focus_window_execute(params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
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

def focus_window_verify(params: Dict[str, Any], context: ExecutionContext, result:ActionResult)->VerifyResult:
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

"""
class MinimizeWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "minimize_window"

    @property
    def supports_verification(self)->bool:
        return True
"""

def minimize_window_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
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

def minimize_window_execute(params:Dict[str,Any], context:ExecutionContext)->ActionResult:
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

def minimize_window_verify(params:Dict[str, Any], context: ExecutionContext, result: ActionResult)->VerifyResult:
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

"""
class MaximizeWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "maximize_window"
    
    @property
    def supports_verification(self)->bool:
        return True
"""

def maximize_window_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
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

def maximize_window_execute(params:Dict[str,Any], context:ExecutionContext)->ActionResult:
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
    
def maximize_window_verify(params:Dict[str,Any], context:ExecutionContext, result: ActionResult)->VerifyResult:
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

"""
class RestoreWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "restore_window"
    
    @property
    def supports_verification(self)->bool:
        return True
"""

def restore_window_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
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

def restore_window_execute(params:Dict[str, Any], context:ExecutionContext)->ActionResult:
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

def restore_window_verify(params:Dict[str,Any], context:ExecutionContext, result: ActionResult)->VerifyResult:
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
        
"""
class CloseWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "close_window"
    
    @property
    def supports_verification(self)->bool:
        return True
"""

def close_window_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
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

def close_window_execute(params: Dict[str, Any], context: ExecutionContext)->ActionResult:
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
    
def close_window_verify(params:Dict[str,Any], context:ExecutionContext, result: ActionResult)->VerifyResult:
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
"""   
def find_element_validate(params:Dict[str,Any])-> Tuple[bool, Optional[str]]:
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

def find_element_execute(params:Dict[str,Any], context:ExecutionContext)->ActionResult:
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

            result = _find_element_find_via_ui_automation(
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
                result = _find_element_find_via_visual(
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
 
def _find_element_find_via_ui_automation(query:str, element_type:Optional[str], hwnd:int)->Optional[Tuple[UIElement, ElementReference]]:
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
    
def _find_element_find_via_visual(self, query:str, element_type:Optional[str], hwnd:int)->Optional[Tuple[VisualElement, ElementReference]]:
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

def find_element_verify(params:Dict[str,Any], context: ExecutionContext, result: ActionResult)->VerifyResult:
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

FIND_WINDOW_SCHEMA = {
    "title"     : {"type": 'str', 'required': True, 'description': 'title of the window'},
    'hwnd'      : {'type': 'int', 'required': False,'description': 'hwnd of the window'}
}
VERIFY_WINDOW_SCHEMA = {
    "title|expected_title|query"    : {"type": "str", "required" : True, "description": "the title (expected) of the opening window"},
    "timeout"                       : {"type": "str", "required" : False, "description":"wait for the window to open"}
}
FOCUS_WINDOW_SCHEMA = {
    "title"     : {"type": 'str', 'required': False, 'description': 'title of the window'},
    'hwnd'      : {'type': 'int', 'required': True,  'description': 'hwnd of the window'}
}
MINIMIZE_WINDOW_SCHEMA = {
    "title"     : {"type": 'str', 'required': False, 'description': 'title of the window'},
    'hwnd'      : {'type': 'int', 'required': True,  'description': 'hwnd of the window'}
} 
MAXIMIZE_WINDOW_SCHEMA = {
    "title"     : {"type": 'str', 'required': False, 'description': 'title of the window'},
    'hwnd'      : {'type': 'int', 'required': True,  'description': 'hwnd of the window'}
} 
RESTORE_WINDOW_SCHEMA = {
    "title"     : {"type": 'str', 'required': False, 'description': 'title of the window'},
    'hwnd'      : {'type': 'int', 'required': True,  'description': 'hwnd of the window'}
} 
CLOSE_WINDOW_SCHEMA = {
    "title"     : {"type": 'str', 'required': False, 'description': 'title of the window'},
    'hwnd'      : {'type': 'int', 'required': True,  'description': 'hwnd of the window'}
} 
FIND_ELEMENT_SCHEMA = {
    "query"       : {"type": "str", "required": True, "description": "name of the elemnt"},
    "element_type": {"type": "str", "required": False, "description": "Type of button"},
    "timeout"     : {"type": "float", "required": False, "description": "try for these many seconds till the element appears"},
    "cache_as"    : {"type": "str", "required": True, "description": "cache the element under this name"}

}   
def register_window_tools(executor: PlanExecutor):
    """Tools related to window operations -> \n
    - find_window  ->  find window among the open windows\n
    - verify_window  ->  verify the presence of the widow\n
    - focus_window  ->  focus on the specified window\n
    - minimize_window  ->  minimize the given window\n
    - maximize_window  ->  maximize the given window\n
    - restore_window  ->  restore the given window\n
    - close_window  ->  close the given window\n
    - find_element  ->  find the given element in the window\n
    """
    executor.register(
        name="find_window",
        schema=FIND_WINDOW_SCHEMA,
        impl=find_window_execute,
        domain="window",
        validate_fn=find_window_validate,
        verify_fn=find_window_verify,
        description="find window among the open windows"
    )
    executor.register(
        name='verify_window',
        schema=VERIFY_WINDOW_SCHEMA,
        impl=verify_window_execute,
        domain='window',
        validate_fn=verify_window_validate,
        supports_verification=False,
        description="verify the presence of the widow"
    )
    executor.register(
        name="focus_window",
        schema=FOCUS_WINDOW_SCHEMA,
        impl=focus_window_execute,
        domain="window",
        validate_fn=focus_window_validate,
        verify_fn=focus_window_verify,
        description="focus on the specified window"
    )
    executor.register(
        name="minimize_window",
        schema=MINIMIZE_WINDOW_SCHEMA,
        impl=minimize_window_execute,
        domain="window",
        validate_fn=minimize_window_validate,
        verify_fn=minimize_window_verify,
        description="minimize the given window"
    )
    executor.register(
        name="maximize_window",
        schema=MAXIMIZE_WINDOW_SCHEMA,
        impl=maximize_window_execute,
        domain="window",
        validate_fn=maximize_window_validate,
        verify_fn=maximize_window_verify,
        description="maximize the given window"
    )
    executor.register(
        name="restore_window",
        schema=RESTORE_WINDOW_SCHEMA,
        impl=restore_window_execute,
        domain="window",
        validate_fn=restore_window_validate,
        verify_fn=restore_window_verify,
        description="restore the given window"
    )
    executor.register(
        name="close_window",
        schema=CLOSE_WINDOW_SCHEMA,
        impl=close_window_execute,
        domain="window",
        validate_fn=close_window_validate,
        verify_fn=close_window_verify,
        description="close the given window"
    )
    executor.register(
        name="find_element",
        schema=FIND_ELEMENT_SCHEMA,
        impl=find_element_execute,
        domain="window",
        validate_fn=find_element_validate,
        verify_fn=find_element_verify,
        description="find the given element in the window",
        requires_screen=True,
    )

"""
Previous

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
                                                             
"""