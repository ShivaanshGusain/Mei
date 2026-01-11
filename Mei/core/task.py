
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple,TYPE_CHECKING
from enum import Enum, auto
from datetime import datetime
import uuid
from abc import ABC, abstractmethod
from .config import TabInfo
from .config import ActionResult, VerifyResult
class TaskStatus(Enum):
    """Status of a task."""
    PENDING = auto()
    UNDERSTANDING = auto()
    PLANNING = auto()
    EXECUTING = auto()
    VERIFYING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class StepStatus(Enum):
    """Status of a single step."""
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    SKIPPED = auto()


@dataclass
class Intent:
    """
    What the user wants to achieve.
    Extracted from the natural language command.
    """
    action: str                          # e.g., "search", "open", "click", "type"
    target: Optional[str] = None         # e.g., "youtube", "calculator", "save button"
    parameters: Dict[str, Any] = field(default_factory=dict)  # e.g., {"query": "cats"}
    confidence: float = 0.0
    raw_command: str = ""
    
    def __str__(self):
        return f"Intent({self.action}, target={self.target}, params={self.parameters})"

class AppBridge(ABC):
    @property
    @abstractmethod
    def app_type(self)-> str:
        '''return app type: 'browser','explorer', etc...'''
        pass
    @property
    @abstractmethod
    def supported_process(self)->List[str]:
        '''returns list of process names this handles,
        eg: ['chrome.exe','firefox.exe']'''
        pass
    @property
    @abstractmethod
    def is_connected(self)->bool:
        ''' Is the bridge active and connected,
        eg: Returns true if websocket to extension is open.'''
        pass
    @abstractmethod
    def get_tabs(self, hwnd:int)->List[TabInfo]:
        '''Get tab/children for a window, returns a lit of tab info'''
    @abstractmethod
    def switch_to_tab(self, hwnd: int, tab_id: str)->bool:
        ''' switch to specific tab'''
        pass
    ''' Optional '''
    def close_tab(self, hwnd:int, tab_id:str)->bool:
        '''closing a specific tab. Optional, default - False'''
        return False
    def navigate(self, hwnd:int, target:str)->bool:
        '''Navigate to the target (url, folder, etc), Browser/Explorer go to path.'''
        return False

class ActionHandler(ABC):
    @property
    @abstractmethod
    def action_name(self)->str:
        """
        Unique identifier for this action
        Must match exactly one of the planner's VALID_ACTIONS:
            "launch_app","terminate_app","focus_window", "minimize_window",
            "maximize_window","type_text","hotkey","click","scroll","navigate_url",
            "wait","find_element"

        Returns:f
            str: The action name ( eg. "focus_window")
        
        Example:
            return "focus_window"
        """
        pass
    @property
    def supports_verification(self)->bool:
        """
        Can it verify its own results.
        Override and return True if handler implements verift()
        Used by Executor to decide whether to call verify()
        
        Handlers that SHOULD support verification:
        - focus_window
        - minimize_window (can check IsIconic)                  
        - maximize_window (can check window placement)          
        - restore_window (can check not minimized/maximized)    
        - close_window (can check window no longer exists)      
        - launch_app (can check process running + window exists)
        - terminate_app (can check process no longer running)   
        - find_element (can check element was found)            
                                                                
        Handlers that CANNOT meaningfully verify:                   
        - type_text (cannot verify text appeared correctly)     
        - hotkey (cannot verify hotkey effect)                  
        - click (cannot verify click effect)                    
        - scroll (cannot verify scroll happened)                
        - wait (nothing to verify)                              
        - navigate_url (would need browser bridge)              
                                                                    
        Returns:                                                    
            bool: False by default, override to return True         
        """                                                         
        return False                                                
                                                            
    def requires_visual_fallback(self)->bool:
        """                                                      
        Whether this handler should try visual detection if UI   
        Automation fails.                                        
                                                                
        Only relevant for handlers that find UI elements:        
            - click (when query is element name, not coordinates)
            - find_element                                       
                                                                
        Returns:                                                 
            bool: False by default, override to return True      
        """                                                      
        return False             

    @abstractmethod
    def validate(self,params:Dict[str,Any])->Tuple[bool, Optional[str]]:     
        """                                                              
        Validate parameters BEFORE execution.                            
                                                                        
        Called by Executor before execute(). If validation fails,        
        execute() is never called and step fails immediately.            
                                                                        
        Validation should check:                                         
            1. Required parameters are present                           
            2. Parameter types are correct                               
            3. Parameter values are reasonable                           
                                                                        
        Args:                                                            
            params: Dictionary of parameters from Step.parameters        
                    e.g., {"query": "notepad"} or {"keys": ["ctrl", "c"]}
                                                                        
        Returns:                                                         
            Tuple of (is_valid, error_message)                           
            - If valid: (True, None)                                     
            - If invalid: (False, "Human readable error message")        
                                                                        
        Example for focus_window:                                        
            if "query" not in params and "hwnd" not in params:           
                return (False, "Missing required parameter: 'query' or 'hwnd'")│
            if "query" in params and not params["query"]:                
                return (False, "Parameter 'query' cannot be empty")      
            return (True, None)                                          
                                                                        
        Example for hotkey:                                              
            if "keys" not in params:                                     
                return (False, "Missing required parameter: 'keys'")     
            if not isinstance(params["keys"], list):                     
                return (False, "Parameter 'keys' must be a list")        
            if len(params["keys"]) == 0:                                 
                return (False, "Parameter 'keys' cannot be empty")       
            return (True, None)                                          
        """                                                              
        pass                                                             

    @abstractmethod
    def execute(self, params:Dict[str,Any], context:Any)->ActionResult:
        """
        Execute the action.
        Called by Executor after validate() passes. 
        This method performs the actual system interaction.

        IMPORTANT RULES:
            1. Do NOT validate params here ( already done)
            2. Do NOT raise exceptions - catch and return ActionResult
            3. Update context when appropriate ( e.g set current_window )
            4. Return meaninful data in ActionResult.data
            5. set method_used to incicate how action was performed.
        
        Args:
            params: Validate parameters from Step.parameters
            context: ExecutionContext instance with shared state
                - context.current_window: Current WindowInfo
                - context.get_element(name): Get cached element
                - context.set_current_window(window): Update window
                - context.store_element(name, ref): Cache element
            
        Returns:
            ActionResult with:
                - success: True if action completed without error
                - data: Relevent output data ( e.g {"hwnd": 12345})
                - error: Error message if failed ( None if success ) 
                - method_used: HOw action was performed
            
        Method_used values:
            - "window_manager": Used WindowManager
            - "process_manager": Used ProcessManager
            - "ui_automation": Used UIAutomationManager
            - "visal_fallback": Used VisualAnalyzer
            - "webbrowser": Used webbrowser module
            - "native": Used time.sleep or similar
        
        Example for focus_window:
            try:
                query = params.get("query")
                hwnd = params.get("hwnd")

                window_manager = get_window_manager()

                if hwnd:
                    window = window_manager.get_window_by_hwnd(hwnd)
                else:
                    window = window_manager.find_window(query)
                
                if not window:
                    return ActionResult(
                        success= False,
                        error = f"Window not found: {query or hwnd}"
                    )
                
                success = window_manager.focus_window(window.hwnd)

                if success:
                    context.set_current_window(window)
                    return ActionResult(
                        success= True,
                        data= {"hwnd": window.hwnd, "title":window.title},
                        method_used="window_manager"
                    )

                else:
                    return ActionResult(
                        success= False,
                        error="Failed to focus window"
                    )
        """
        pass

    def verify(self,params: Dict[str, Any], context: Any, result: ActionResult)->VerifyResult:
        """
        Verify the action achieved its immediate goal.

        Called by Executor after execute() if supports_verification is True. 
        Override this method in handlers that can verify.

        NOTE: This is STEP-LEVEL verificaiton, not GOAL-LEVEL.
            - Step verification: "Did focus_window make window foreground?"
            - Goal verification: "Did user's search intent succeed?"
              (Goal verification is Stage 3, handled by GoalVerifier)
        
        Default implementation returns unverified with low confidence.
        This is appropriate for handlers that cannot verify.

        Args:
            params: Same parameters from execute()
            context: Current ExecutionContext
            result: The ActionResult from execute()
                    Useful for accessing data like hwnd

        Returns:
            VerifyResult with:
                - verified: True if verification passed
                - confience: How sure we are (0.0 to 1.0)
                - reason: Explanation of verification result
        Confidence guidelines:                                            
            - 0.95: Direct API check confirmed (e.g., GetForegroundWindow)
            - 0.85: Indirect check confirmed (e.g., window exists)        
            - 0.70: Visual check confirmed                                
            - 0.50: Cannot verify, assumed okay                           
                                                                        
        Example for focus_window:                                         
            hwnd = result.data.get("hwnd")                                
            if not hwnd:                                                  
                return VerifyResult(                                      
                    verified=False,                                       
                    confidence=0.9,                                       
                    reason="No hwnd in result to verify"                  
                )                                                         
                                                                        
            window_manager = get_window_manager()                         
            foreground = window_manager.get_foreground_window()           
                                                                        
            if foreground and foreground.hwnd == hwnd:                    
                return VerifyResult(                                      
                    verified=True,                                        
                    confidence=0.95,                                      
                    reason="Window confirmed as foreground"               
                )                                                         
            else:                                                         
                return VerifyResult(                                      
                    verified=False,                                       
                    confidence=0.90,                                      
                    reason="Window not in foreground"                     
                )                                                         
        """                                                               
        from  .config import VerifyResult  
        return VerifyResult(                                              
            verified=True,                                                
            confidence=0.5,                                               
            reason="Verification not supported by this handler"          
        )                                                                 
        
@dataclass
class Step:
    """
    A single step in an execution plan.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    action: str = ""                     # Action type: "focus_window", "type", "click", etc.
    parameters: Dict[str, Any] = field(default_factory=dict)
    description: str = ""                # Human-readable description
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Verification
    verification_method: Optional[str] = None  # How to verify this step worked
    verified: bool = False
    
    @property
    def duration_ms(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None


@dataclass
class Plan:
    """
    A plan to accomplish a task.
    Contains ordered list of steps.
    """
    steps: List[Step] = field(default_factory=list)
    strategy: str = ""                   # e.g., "reuse_window", "new_window"
    reasoning: str = ""                  # Why this plan was chosen
    created_at: datetime = field(default_factory=datetime.now)
    
    @property
    def current_step_index(self) -> int:
        """Get index of current step (first non-completed)."""
        for i, step in enumerate(self.steps):
            if step.status in [StepStatus.PENDING, StepStatus.RUNNING]:
                return i
        return len(self.steps)
    
    @property
    def current_step(self) -> Optional[Step]:
        """Get current step."""
        idx = self.current_step_index
        if idx < len(self.steps):
            return self.steps[idx]
        return None
    
    @property
    def is_complete(self) -> bool:
        """Check if all steps are done."""
        return all(s.status in [StepStatus.COMPLETED, StepStatus.SKIPPED] 
                   for s in self.steps)
    
    @property
    def has_failed(self) -> bool:
        """Check if any step failed."""
        return any(s.status == StepStatus.FAILED for s in self.steps)
    
    @property
    def progress(self) -> float:
        """Get progress as percentage (0-100)."""
        if not self.steps:
            return 100.0
        completed = sum(1 for s in self.steps 
                       if s.status in [StepStatus.COMPLETED, StepStatus.SKIPPED])
        return (completed / len(self.steps)) * 100


@dataclass 
class Task:
    """
    A complete task the agent is working on.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    raw_command: str = ""                # Original user command
    intent: Optional[Intent] = None      # Parsed intent
    plan: Optional[Plan] = None          # Execution plan
    status: TaskStatus = TaskStatus.PENDING
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)  # System state when task started
    
    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Result
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    
    @property
    def duration_ms(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            'id': self.id,
            'raw_command': self.raw_command,
            'intent': {
                'action': self.intent.action,
                'target': self.intent.target,
                'parameters': self.intent.parameters,
            } if self.intent else None,
            'plan_steps': [
                {
                    'action': s.action,
                    'parameters': s.parameters,
                    'status': s.status.name,
                }
                for s in (self.plan.steps if self.plan else [])
            ],
            'status': self.status.name,
            'created_at': self.created_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'result': self.result,
            'error': self.error,
        }