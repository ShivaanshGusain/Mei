# mei/core/events.py
"""
Event system for component communication.
Components don't talk to each other directly - they emit events.
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any, Optional
from datetime import datetime
import uuid
import threading


class EventType(Enum):
    """All event types in the system."""
    
    # Lifecycle
    AGENT_STARTED = auto()
    AGENT_STOPPED = auto()
    
    # Audio
    WAKE_WORD_DETECTED = auto()
    SPEECH_STARTED = auto()
    SPEECH_ENDED = auto()
    COMMAND_RECEIVED = auto()
    SPEECH_RECEIVED = auto()
    TRANSCRIBE_COMPLETED = auto()
    
    # Screen
    MONITOR_REFRESHED = auto()
    MONITOR_SCREENSHOT = auto()
    REGION_SCREENSHOT = auto()
    WINDOW_CAPTURED = auto()
    SCREENSHOT_COMPARED = auto()
    SCREENSHOT_SAVED = auto()

    # Visual Analysis
    VISUAL_ANALYSIS_STARTED = auto()
    VISUAL_ANALYSIS_COMPLETED = auto()
    VISUAL_ELEMENT_FOUND = auto()
    VISUAL_ELEMENT_NOT_FOUND = auto()
    VISUAL_TEXT_EXTRACTED = auto()
    OMNIPARSER_LOADED = auto()
    OMNIPARSER_ERROR = auto()
    OCR_COMPLETED = auto()
    OMNIPARSER_UNLOADED = auto()
    
    #LLM
    LLM_LOADING = auto()
    LLM_LOADED = auto()
    LLM_UNLOADED = auto()
    # Understanding
    INTENT_RECOGNIZED = auto()
    ENTITIES_EXTRACTED = auto()
    
    # Planning
    PLAN_CREATED = auto()
    PLAN_STEP_STARTED = auto()
    PLAN_STEP_COMPLETED = auto()
    PLAN_STEP_FAILED = auto()
    PLAN_COMPLETED = auto()
    PLAN_FAILED = auto()
    
    # Execution
    ACTION_STARTED = auto()
    ACTION_COMPLETED = auto()
    ACTION_FAILED = auto()
    
    # System
    WINDOW_CHANGED = auto()
    WINDOW_CLOSED = auto()
    
    TAB_CLOSED = auto()
    TAB_OPENED = auto()
    APP_LAUNCHED = auto()
    APP_CLOSED = auto()
    
    # Memory
    MEMORY_STORED = auto()
    MEMORY_RETRIEVED = auto()
    
    # User Interaction
    CONFIRMATION_NEEDED = auto()
    CONFIRMATION_RECEIVED = auto()
    
    # Errors
    ERROR = auto()


@dataclass
class Event:
    """An event in the system."""
    type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source: str = "unknown"


# Type alias for event handlers
EventHandler = Callable[[Event], None]


class EventBus:
    """
    Central event bus for the application.
    Components publish events here, others subscribe to receive them.
    """
    
    _instance: Optional["EventBus"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._global_handlers: List[EventHandler] = []
        self._handler_lock = threading.Lock()
        self._event_history: List[Event] = []
        self._max_history = 100
        
        self._initialized = True
    
    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        with self._handler_lock:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)
    
    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to ALL events (useful for logging)."""
        with self._handler_lock:
            self._global_handlers.append(handler)
    
    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Unsubscribe from an event type."""
        with self._handler_lock:
            if event_type in self._handlers:
                try:
                    self._handlers[event_type].remove(handler)
                except ValueError:
                    pass
    
    def emit(self, event: Event) -> None:
        """Emit an event to all subscribers."""
        # Store in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
        
        # Call handlers
        with self._handler_lock:
            handlers = list(self._handlers.get(event.type, []))
            global_handlers = list(self._global_handlers)
        
        for handler in handlers + global_handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"[EventBus] Handler error: {e}")
    
    def emit_simple(
        self, 
        event_type: EventType, 
        source: str = "unknown",
        **data
    ) -> Event:
        """Convenience method to emit an event."""
        event = Event(type=event_type, data=data, source=source)
        self.emit(event)
        return event
    
    def get_history(self, event_type: Optional[EventType] = None) -> List[Event]:
        """Get event history, optionally filtered by type."""
        if event_type is None:
            return list(self._event_history)
        return [e for e in self._event_history if e.type == event_type]


# Global access
def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    return EventBus()


def emit(event_type: EventType, source: str = "unknown", **data) -> Event:
    """Convenience function to emit an event."""
    return get_event_bus().emit_simple(event_type, source, **data)


def subscribe(event_type: EventType, handler: EventHandler) -> None:
    """Convenience function to subscribe to events."""
    get_event_bus().subscribe(event_type, handler)