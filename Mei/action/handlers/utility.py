import time
from typing import Dict, Any, Tuple, Optional
from datetime import datetime

from ...core.task import ActionHandler
from ...core.config import ActionResult,VerifyResult,ElementReference

from ...perception.System.windows import get_window_manager
from ...perception.System.accessibility import UIAutomationManager

from ...perception.Visual.screen import ScreenCapture
from ...perception.Visual.analyzer import get_visual_analyzer

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

class FindElementHandler(ActionResult):
    pass