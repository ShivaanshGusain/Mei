import time
from typing import Dict, Any, Optional, List, Type, Tuple, Callable
from datetime import datetime

from ..core.config import ActionResult, VerifyResult, get_config
from ..core.events import EventType, Event, emit, subscribe, get_event_bus
from ..cognition.observation import get_observation_builder
from ..core.state import AgentState, get_state_machine

from .context import ExecutionContext
from .toolspec import ToolSpec
 
from .debug.logger import get_execution_logger

# from .handlers.window import get_window_handlers
# from .handlers.app import get_app_handlers
# from .handlers.input import get_input_handlers
# from .handlers.navigation import get_navigation_handlers
# from .handlers.utility import get_util_handers

from .handlers import register_all_tools #[TODO]


DEFAULT_STEP_DELAY = 0.1
MAX_PLAN_DURATION = 300.0

LOG_VERIFICATION_FAILURES = True
VERIFY_STEPS = True

class PlanExecutor:
    def __init__(self, auto_subscribe: bool = True):
        # self._handlers: Dict[str, ActionHandler] = {} 
        # self._register_all_handlers()

        #[UPDATE] Keeping the above line of code as comments

        self._tools: Dict[str, ToolSpec] = {}
        self._is_executing = False
        self._current_context: Optional[ExecutionContext] = None
        self._task_queue = __import__('queue').Queue()

        self._logger = get_execution_logger()
        self._state_machine = get_state_machine()
        self._config = get_config()
        
        # Avoid circular import by doing this inside the method or initializing lazily
        from .handlers import register_all_tools
        register_all_tools(self)
        
        from ..cognition.planning.prompt_builder import TOOL_REGISTRY
        missing = set(TOOL_REGISTRY) - set(self._tools)
        if missing:
            print(f"[WARNING] Tools in catalog but not registered: {missing}")
            for ghost in missing:
                TOOL_REGISTRY.pop(ghost, None)

        if auto_subscribe:
            self.start()
    """
    def _register_all_handlers(self)->None:
        all_handlers = []
        try:
            all_handlers.extend(get_window_handlers())
        except Exception as e:
            print(f"Failed to load window handlers: {e}")
        
        try:
            all_handlers.extend(get_app_handlers())
        except Exception as e:
            print(f"Failed to load app handlers: {e}")
        
        try:
            all_handlers.extend(get_input_handlers())
        except Exception as e:
            print(f"Failed to load input handlers: {e}")

        try:
            all_handlers.extend(get_navigation_handlers())
        except Exception as e:
            print(f"Failed to load navigation handlers: {e}")
        
        try:
            all_handlers.extend(get_util_handers())
        except Exception as e:
            print(f"Failed to load utility handlers: {e}")

        for handler in all_handlers:
            action_name = handler.action_name
            if action_name in self._handlers:
                print(f"Duplicate handler for '{action_name}'")
            self._handlers[action_name] = handler
        
        print(f"Registered {len(self._handlers)} handlers")
        for name in sorted(self._handlers.keys()):
            print(f" - {name}")

    def register_handler(self, handler: ActionHandler)->None:
        
        action_name = handler.action_name
        self._handlers[action_name] = handler
        print(f"Registered handler: {action_name}")
    """
    
    def register(self, name: str, impl: Callable, domain: str, *,
                 schema: Dict[str,Any] = None,
                 validate_fn: Callable = None,
                 verify_fn: Callable = None,
                 requires_screen: bool = False,
                 requires_browser: bool = False,
                 requires_window: bool = False,
                 requires_ui_tree: bool = False,
                 cost: int = 1,
                 supports_verification: bool = True,
                 description: str = "") -> None:
        """Builds a ToolSpec from args and store it."""
        spec = ToolSpec(
            name = name,
            domain= domain,
            impl=impl,
            schema=schema or {},
            validate_fn=validate_fn,
            verify_fn=verify_fn,
            requires_screen=requires_screen,
            requires_browser=requires_browser,
            requires_window=requires_window,
            requires_ui_tree=requires_ui_tree,
            cost=cost,
            description=description,
            supports_verification=supports_verification
        )
        if name in self._tools:
            print(f"Overwriting tool '{name}'")
        self._tools[name] = spec
        print(f"Registered tool: {name} [{domain}]")

    
    """
    def get_handler(self, action_name:str)->Optional[ActionHandler]:
        return self._handlers.get(action_name)
    """
    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)
    
    """Addition"""
    def list_tools(self)->List[Dict[str,Any]]:
        """Expose tool metadata for the planner's context window."""
        return[
            {
                "name": t.name,
                "domain":t.domain,
                "description":t.description,
                "schema":t.schema,
                "cost":t.cost,
                "supports_verification":t.supports_verification,
            }
            for t in self._tools.values()
        ]
    
    def list_actions(self)->List[str]:
        # return list(self._handlers.keys())
        return list(self._tools.keys())
    
    def start(self)->None:
        print("Started executor")
    
    def stop(self)->None:
        self._is_executing = False
        print("Stopped")



    def execute_single_action(self, action:str, parameters: Dict[str, Any], context: Optional[ExecutionContext] = None)->ActionResult:
        # handler = self.get_handler(action)
        # if not handler:
        
        tool = self.get_tool(action)
        if not tool:
            return ActionResult(
                success= False,
                error = f"No handler for action: {action}"
            )
        
        PATH_KEYS = ("path", "target_path", "destination", "source", "directory")
        for key in PATH_KEYS:
            if key in parameters and isinstance(parameters[key], str):
                from pathlib import Path
                raw = parameters[key]
                p = Path(raw)
                if not p.is_absolute():
                    parts = p.parts
                    if parts and parts[0].lower() in {"desktop", "documents", "downloads", "pictures", "music", "videos"}:
                        home = Path.home()
                        candidate = home / Path(*parts)
                        onedrive = home / "OneDrive" / Path(*parts)
                        if onedrive.parent.exists() and onedrive.exists():
                            p = onedrive
                        else:
                            p = candidate
                parameters[key] = str(p.expanduser().resolve())

        # is_valid, error = handler.validate(parameters)
        if tool.validate_fn:
            is_valid, error = tool.validate_fn(parameters)
        else:
            is_valid, error = True, None

        if not is_valid:
            return ActionResult(
                success=False,
                error = f"Validation failed: {error}"
            )
        
        # If no external context was provided, create a minimal one
        if context is None:
            dummy_intent = Intent(
                action=action,
                target=None,
                parameters=parameters,
                confidence=0.1,
                raw_command=f"direct:{action}"
            )
            dummy_step = Step(
                id=f"direct_{action}",
                action=action,
                parameters=parameters,
                description=f"Direct execution of {action}"
            )

            dummy_plan = Plan(
                steps=[dummy_step],
                strategy="direct_execution",
                reasoning="Direct action execution"
            )

            context = ExecutionContext(plan = dummy_plan, intent= dummy_intent)

        try:
            # return handler.execute(parameters,context)
            return tool.impl(parameters,context)
        except Exception as e:
            return ActionResult(
                success=False,
                error = f"Exception: {str(e)}"
            )
        
    def get_current_context(self)->Optional[ExecutionContext]:
        return self._current_context
    

    @property
    def is_executing(self)->bool:
        return self._is_executing
    
_executor_instance:Optional[PlanExecutor] = None


def get_executor(auto_subscribe:bool = True)-> PlanExecutor:
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = PlanExecutor(auto_subscribe=auto_subscribe)
    return _executor_instance

__all__ = [
    'PlanExecutor',
    'get_executor',
]
