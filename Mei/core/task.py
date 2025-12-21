# mei/core/task.py
"""
Task representation - what the agent is trying to accomplish.
A Task has an Intent, a Plan, and execution Status.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum, auto
from datetime import datetime
import uuid
from abc import ABC, abstractmethod
from .config import TabInfo
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