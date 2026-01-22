import time
from typing import Dict, Any, Tuple, Optional
from datetime import datetime

from ...core.task import ActionHandler
from ...core.config import ActionResult,VerifyResult,ElementReference

from ...perception.System.windows import get_window_manager
from ...perception.System.accessibility import UIAutomationManager, UIElement

from ...perception.Visual.screen import ScreenCapture
from ...perception.Visual.analyzer import get_visual_analyzer, VisualElement

from ..context import ExecutionContext

DEFAULT_WAIT_SECONDS = 1.0
MAX_WAIT_SECONDS = 30.0
DEFAULT_FIND_TIMEOUT = 5.0
FIND_RETRY_INTERVAL = 0.5

_ui_automation_manager: Optional[UIAutomationManager] = None
_screen_capture: Optional[ScreenCapture] = None

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

class WaitHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return 'wait'
    
    @property
    def supports_verification(self)->bool:
        return False
    
    def validate(self, params:Dict[str,Any])-> Tuple[bool, Optional[str]]:
        if 'seconds' not in params:
            return (False, "Missing required parameter: 'seconds'")
        
        try:
            seconds = float(params['seconds'])
        except (ValueError, TypeError):
            return (False, "Parameter 'seconds' must be a number'")
        
        if seconds <=0:
            return (False, "Parameter 'seconds' must be positive")
        
        if seconds> MAX_WAIT_SECONDS:
            return (False, f"Parameter 'seconds' cannto exceed {MAX_WAIT_SECONDS}")
        
        return (True, None)
    
    def execute(self, params:Dict[str,Any], context: ExecutionContext)->ActionResult:
        try:
            seconds = float(params['seconds'])
            reason = params.get('reason', 'No reason specified')

            context.set_variable('last_wait_seconds', seconds)
            context.set_variable('last_wait_reason', reason)

            start_time = time.time()
            time.sleep(seconds)
            actual_wait = time.time() - start_time

            return ActionResult(
                success=True,
                data={
                    'requested_seconds': seconds,
                    'actual_seconds':round(actual_wait,3),
                    'reason':reason
                },
                method_used='time_sleep'
            )

        except Exception as e:
            return ActionResult(
                success=False,
                error = f"Exception during wait: {str(e)}",
                method_used='time_sleep'
            )

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
        if 'query' not in params:
            return (False, "Missing required parameter: 'query'")
        
        query = params['query']
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
            query = str(params['query']).strip()
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
        
UTIL_HANDLERS = [WaitHandler, FindElementHandler]
def get_util_handers()->list:
    return [handler() for handler in UTIL_HANDLERS]

__all__ = [
    'WaitHandler',
    'FindElementHandler',
    'UTIL_HANDLERS',
    'get_util_handers'
]
