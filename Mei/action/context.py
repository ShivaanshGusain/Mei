from typing import Dict, Any, Optional, List
from datetime import datetime
from ..core.config import WindowInfo, ElementReference, ActionResult
from ..core.task import Plan, Intent, Step
from ..perception.System.windows import get_window_manager


class ExecutionContext:

    def __init__(self, plan:Plan, intent: Intent):
        self.plan  = plan
        self.intent = intent
        
        self._current_window:Optional[WindowInfo] = None
        self._found_elements:Dict[str, ElementReference] = {}
        self.step_results: List[ActionResult] = []

        self.start_time: datetime = datetime.now()

        self.current_step_index: int = 0

        self.variables:Dict[str, Any] = {}

    @property
    def current_window(self) -> Optional[WindowInfo]:
        # If returns None, the handler should use get_foreground_window() or return an error
        return self._current_window
    
    def set_current_window(self,window:Optional[WindowInfo])->None:
        old_hwnd = self._current_window.hwnd if self._current_window else None
        new_hwnd = window.hwnd if window else None
    
        if old_hwnd!= new_hwnd:
            self._found_elements.clear()
        self._current_window = window

    def get_current_window_or_foreground(self)->Optional[WindowInfo]:
        if self._current_window is not None:
            return self._current_window
        try:
            window_manager = get_window_manager()
            foreground = window_manager.get_foreground_window()
            if foreground:
                return foreground
        except Exception:
            pass

        return None 

    def store_element(self,name:str, reference: ElementReference)->None:
        normalized_name = name.lower().strip()
        self._found_elements[normalized_name] = reference
    
    def get_element(self, name:str)->Optional[ElementReference]:
        normalized_name = name.lower().strip()
        reference = self._found_elements.get(normalized_name)
        if reference is None:
            return None
        if reference.is_stale():
            del self._found_elements[normalized_name]
            return None
        return reference

    def has_element(self, name:str)->bool:
        return self.get_element(name) is not None

    def clear_elements(self)->None:
        self._found_elements.clear()
    
    def add_step_result(self, result:ActionResult)->None:
        self.step_results.append(result)
    
    def get_last_result(self)->Optional[ActionResult]:
        if self.step_results:
            return self.step_results[-1]
        return None
    
    def set_variable(self,key:str, value:Any)->None:
        self.variables[key] = value

    def get_variable(self, key:str, default:Any = None)->Any:
        return self.variables.get(key, default)
    
    def elapsed_time_ms(self)->float:
        elapsed = datetime.now() - self.start_time
        return elapsed.total_seconds()*1000
    
    def get_current_step(self)->Optional["Step"]:
        from ..core.task import Step
        if 0 <= self.current_step_index < len(self.plan.steps):
            return self.plan.steps[self.current_step_index]
        return None

    def to_dict(self)->Dict[str,Any]:
        return {
            "intent":{
                'action':self.intent.action,
                'target':self.intent.target,
                'parameters': self.intent.parameters,
                'raw_command':self.intent.raw_command
            },
            'plan': {
                'strategy':self.plan.strategy,
                'step_count': len(self.plan.steps),
                'steps':[
                    {
                        'action': step.action,
                        'parameters':step.parameters,
                        'description': step.description
                    }
                    for step in self.plan.steps
                ]
        },
        "current_window": {
            'hwnd': self._current_window.hwnd,
            'title': self._current_window.title,
            'process': self._current_window.process_name
        } if self._current_window else None,
        "current_step_index": self.current_step_index,
        "elapsed_ms": self.elapsed_time_ms(),
        'step_results': [
            {
            'success': r.success,
            'method_used': r.method_used,
            'error': r.error
        } for r in self.step_results
        ],
        "variables": self.variables,
        "cached_elements": list(self._found_elements.keys())
        }
    
    
