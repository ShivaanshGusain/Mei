# mei/core/state.py
"""
Global State Machine.
Prevents the agent from doing two conflicting things at once.
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Set
import threading
from .events import emit, EventType

class AgentState(Enum):
    """The high-level mode of the agent."""
    IDLE = auto()           # Waiting for wake word
    LISTENING = auto()      # Recording microphone
    THINKING = auto()       # LLM is generating
    PLANNING = auto()       # Creating step-by-step plan
    EXECUTING = auto()      # Moving mouse/keyboard
    SPEAKING = auto()       # TTS is active
    ERROR = auto()          # Something broke
    STOPPED = auto()        # Shutdown

class StateMachine:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.current_state = AgentState.IDLE
        self.last_state = AgentState.STOPPED
        self.last_transition = datetime.now()
        self._state_lock = threading.Lock()
        
        # Define allowed transitions (Safety rules)
        # e.g., You cannot go from LISTENING straight to EXECUTING (must THINK first)
        self.allowed_transitions = {
            AgentState.IDLE: {AgentState.LISTENING, AgentState.THINKING, AgentState.ERROR, AgentState.STOPPED},
            AgentState.LISTENING: {AgentState.IDLE, AgentState.THINKING, AgentState.ERROR},
            AgentState.THINKING: {AgentState.IDLE, AgentState.PLANNING, AgentState.SPEAKING, AgentState.ERROR},
            AgentState.PLANNING: {AgentState.EXECUTING, AgentState.THINKING, AgentState.ERROR},
            AgentState.EXECUTING: {AgentState.IDLE, AgentState.SPEAKING, AgentState.THINKING, AgentState.ERROR},
            AgentState.SPEAKING: {AgentState.IDLE, AgentState.LISTENING, AgentState.EXECUTING, AgentState.ERROR},
            AgentState.ERROR: {AgentState.IDLE, AgentState.STOPPED},
        }
        self._initialized = True

    def set_state(self, new_state: AgentState) -> bool:
        """
        Attempt to change state. 
        Returns True if successful, False if transition is illegal.
        """
        with self._state_lock:
            if new_state == self.current_state:
                return True
            
            # Check if this move is allowed
            # (We allow forcing ERROR or STOPPED from anywhere)
            if new_state not in [AgentState.ERROR, AgentState.STOPPED]:
                if new_state not in self.allowed_transitions.get(self.current_state, set()):
                    print(f"[StateMachine] BLOCKED: Cannot go {self.current_state.name} -> {new_state.name}")
                    return False

            old_state = self.current_state
            self.last_state = old_state
            self.current_state = new_state
            self.last_transition = datetime.now()
            
            # Announce the change to the rest of the system
            print(f"[State] {old_state.name} -> {new_state.name}")
            emit(EventType.AGENT_STARTED if new_state == AgentState.IDLE else EventType.WINDOW_CHANGED, 
                 source="state_machine", 
                 old_state=old_state.name, 
                 new_state=new_state.name)
            
            return True

    def get_state(self) -> AgentState:
        return self.current_state

# Global accessor
def get_state_machine() -> StateMachine:
    return StateMachine()