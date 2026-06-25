from ..core.config import Observation, ActionResult, VerifyResult
from ..perception.System.windows import get_window_manager
from ..perception.System.process import get_process_manager
from ..perception.System.accessibility import get_accessibility_manager
from typing import Optional, Dict, Any

_APP_ACTIONS = {'launch_app', 'terminate_app'}
_UI_ACTIONS = {"click", "type_text", "find_element", "hotkey"}
_CHECK_RUNNING = {"launch_app", "terminate_app", "close_window"}

class ObservationBuilder:
    """Collects observations signals after a step executes."""

    def __init__(self):
        self._window_manager = get_window_manager()
        self._process_manager = get_process_manager()
        self._accessibility_manager = get_accessibility_manager()

    def build(
            self,
            action: str,
            parameters: Dict[str, Any],
            result: ActionResult,
            verify_result: Optional[VerifyResult] = None,
            target_app: Optional[str] = None
    ) -> Observation:
        """
        Build an Observation from execution result + environment state.
        
        Always collects: result + foreground window (cheap).
        Conditionally collects: target running, focused element (medium).
        """
        obs = Observation(
            action=action,
            parameters=parameters,
            success=result.success,
            error=result.error,
            result_data=result.data or {},
            method_used= result.method_used
        )

        if verify_result is not None:
            obs.verified = verify_result.confidence
            obs.verify_confidence = VerifyResult.confidence
            obs.verify_reason = verify_result.reason

        self._collect_window_state(obs)

        if action in _CHECK_RUNNING and target_app:
            try:
                obs.target_running = self._process_manager.is_running(target_app)
            except:
                pass
        
        if action in _UI_ACTIONS:
            self._collect_focused_element(obs)

        return obs
    
    def _collect_window_state(self, obs:Observation)-> None:
        """Get foreground window info"""
        try:
            fg = self._window_manager.get_foreground_window()
            if fg:
                obs.foreground_window = fg.title[:80]
                obs.foreground_process = fg.process_name
        except:
            pass

        try:
            windows = self._window_manager.get_all_windows()[:5]
            obs.open_windows = [w.title[:40] for w in windows]
        except:
            pass
    
    def _collect_focused_element(self, obs: Observation)->None:
        """Get the currently focused UI element"""
        try:
            element = self._accessibility_manager.get_focused_element()
            if element:
                obs.focused_element = element.name
                obs.focused_element_type = element.control_type
                obs.focused_element_value = element.value
        except:
            pass
    
_builder: Optional[ObservationBuilder] = None

def get_observation_builder()-> ObservationBuilder:
    global _builder
    if _builder is None:
        _builder = ObservationBuilder()
    return _builder