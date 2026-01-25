import threading
import secrets
from typing import Dict, Any, Optional, List
from datetime import datetime

from ..core.config import ConversationTurn, SessionTask,UserCorrection, get_config
from ..core.task import Intent, Plan, Step
from ..core.events import EventType, Event, subscribe, emit, get_event_bus
from .store import get_memory_store, MemoryStore


DEFAULT_MAX_CONVERSATION_TURNS = 20
DEFAULT_MAX_TASK_HISTORY = 50
DEFAULT_PRIOR_CONTENT_LIMIT = 10


class WorkingMemory:
    def __init__(self, auto_subscribe: bool = True):
        self._store: MemoryStore = get_memory_store()

        self._session_id: Optional[str] = None
        self._started_at: Optional[datetime] = None
        self._last_activity:Optional[datetime] = None
        self._is_active:bool = False

        self._conversation_history:List[ConversationTurn] = []
        self._max_conversation_turns:int = DEFAULT_MAX_CONVERSATION_TURNS

        self._task_history:List[SessionTask] = []
        self._max_task_history:int = DEFAULT_MAX_TASK_HISTORY
        self._current_task:Optional[SessionTask] = None

        self._corrections: List[UserCorrection] = []
        self._session_preferences: Dict[str,Any] = {}

        self._prior_context: List[Dict[str,Any]] = []

        self._lock: threading.RLock = threading.RLock()

        self._subscribe_to_events()

    def _subscribe_to_events(self)->None:
        subscribe(EventType.AGENT_STARTED, self._on_agent_started)
        subscribe(EventType.AGENT_STOPPED, self._on_agent_stopped)
        subscribe(EventType.TRANSCRIBE_COMPLETED, self._on_transcribe_completed)
        subscribe(EventType.INTENT_RECOGNIZED, self._on_intent_recognized)
        subscribe(EventType.PLAN_CREATED, self._on_plan_created)
        subscribe(EventType.PLAN_COMPLETED, self._on_plan_completed)
        subscribe(EventType.PLAN_FAILED, self._on_plan_failed)

    def _on_agent_started(self,event:Event)->None:
        
        with self._lock:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            random_suffix = secrets.token_hex(4)
            self._session_id = f"session_{timestamp}_{random_suffix}"

            self._started_at = datetime.now()
            self._last_activity = datetime.now()
            self._is_active = True

            self._conversation_history = []
            self._task_history = []
            self._current_task = None
            self._corrections = []
            self._session_preferences = {}
            self._prior_context = []

            try:
                recent_tasks = self._store.get_task_executions(
                    limit = DEFAULT_PRIOR_CONTENT_LIMIT
                )
                self._prior_context = recent_tasks
            except Exception as e:
                print(f"Could not load prior context: {e}")
            
            try:
                behavior_prefs = self._store.get_preferences_by_category('behavior')
                app_prefs = self._store.get_preferences_by_category('app')
                self._session_preferences.update(behavior_prefs)
                self._session_preferences.update(app_prefs)

            except Exception as e:
                print(f"Could not load preferences: {e}")

            emit( EventType.MEMORY_SESSION_STARTED, source="WorkingMemory", session_id = self._session_id)

            print(f"Session {self._session_id} started")

        
    def _on_transcribe_completed(self, event:Event)->None:
        if not self._is_active:
            return
        
        with self._lock:
            user_text = event.data.get('text', "")
            
            if not user_text or not user_text.strip():
                return
            
            turn = ConversationTurn(
                timestamp=datetime.now(),
                user_input=user_text.strip(),
                intent = None,
                task_id = None,
                success = None,
                agent_response=None
            )

            self._conversation_history.append(turn)

            while len(self._conversation_history) > self._max_conversation_turns:
                self._conversation_history.pop(0)

            self._last_activity = datetime.now()

    def _on_intent_recognized(self, event:Event)->None:
        if not self._is_active:
            return
        
        with self._lock:
            intent = event.data.get('intent')
            
            if intent is None:
                return
            
            if self._conversation_history:
                last_turn = self._conversation_history[-1]
                last_turn.intent = intent
            
            if self._is_potential_correction(last_turn.user_input):
                self._handle_potential_correction(intent)

            self._last_activity = datetime.now()

    def _is_potential_correction(self, user_input:str)->bool:
        lower_input = user_input.lower().strip()

        correction_phrases = [
            'no ',
            'not ',
            'i meant ',
            'i mean',
            'i said',
            'actually',
            'instead',
            'wrong',
            'correction',
            'sorry'
        ]
        
        for phrase in correction_phrases:
            if lower_input.startswith(phrase):
                return True
        return False
    
    def _handle_potantial_correction(self, new_intent:Intent)->None:
        if len(self._conversation_history)<2:
            return
        
        previous_turn = self._conversation_history[-2]
        current_turn = self._conversation_history[-1]

        if previous_turn.intent is None:
            return
        
        if previous_turn.intent.action == new_intent.action:
            if previous_turn.intent.target != new_intent.target:
                pass
            else:
                return
        else:
            if not self._has_explicit_correction_language(current_turn.user_input):
                return
            
        correction = UserCorrection(
            timestamp=datetime.now(),
            original_input=previous_turn.user_input,
            original_intent=previous_turn.intent,
            corrected_input = current_turn.user_input,
            corrected_intent=new_intent,
            context={
                'session_id':self._session_id,
                'turn_index':len(self._conversation_history) -1
            }
        )

        self._corrections.append(correction)

        print(f"recorded correction: {previous_turn.intent.target} -> {new_intent.target}")
    
    def _has_explicit_correction_language(self, text:str)->bool:
        explicit_phrases = ['no ', 'not ', 'i meant', 'i mean', 'wrong']
        lower_text = text.lower()

        return any(phrase in lower_text for phrase in explicit_phrases)
    
    def _on_plan_created(self, event:Event)->None:

        if not self._is_active:
            return
        
        with self._lock:
            plan = event.data.get('plan')
            intent = event.data.get('intent')
            from_cache = event.data.get('from_cache', False)

            if plan is None or intent is None:
                return
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            random_suffix = secrets.token_hex(4)
            task_id = f"exec_{timestamp}_{random_suffix}"

            task = SessionTask(
                task_id= task_id,
                intent = intent,
                plan_strategy=plan.strategy if hasattr(plan,'strategy') else 'unknown',
                started_at=datetime.now(),
                completed_at=None,
                success= None,
                error = None,
                from_cache=from_cache
            )

            self._current_task = task

            if self._conversation_history:
                self._conversation_history[-1].task_id = task_id
            
            self._last_activity = datetime.now()

    
    def _on_plan_completed(self, event:Event)->None:
        if not self._is_active:
            return
        
        if self._current_task is None:
            print("PLAN_COMPLETED but no current task")
            return
        
        with self._lock:
            execution_id = event.data.get("execution_id", self._current_task.task_id)
            duration_ms = event.data.get("duration_ms", 0.0)
            intent = event.data.get("intent", self._current_task.intent)
            plan = event.data.get("plan")
            step_results = event.data.get("step_results", [])
            context = event.data.get("context")

            self._current_task.task_id = execution_id
            self._current_task.completed_at = datetime.now()
            self._current_task.success = True
            self._current_task.error = None

            self._task_history.append(self._current_task)

            while len(self._task_history) > self._max_task_history:
                self._task_history.pop(0)

            completed_task = self._current_task
            self._current_task = None

            if self._conversation_history:
                for turn in reversed(self._conversation_history):
                    if turn.task_id == completed_task.task_id or turn.task_id == execution_id:
                        turn.success = True
                        turn.task_id = execution_id
                        break
                
            self._persist_completed_task(
                execution_id=execution_id,
                intent=intent,
                plan=plan,
                success = True,
                duration_ms = duration_ms,
                step_results = step_results,
                context = context,
                failure_reason = None,
                failure_step_index = None
            )

            emit(
                EventType.MEMORY_STORED,
                source="WorkingMemory",
                execution_id = execution_id,
                success = True
            )

            self._last_activity = datetime.now()

    def _on_plan_failed(self, event:Event)->None:
        if not self._is_active:
            return
        
        if self._current_task is None:
            print("PLAN_FAILED but no current task")
            return
        
        with self._lock():
            execution_id = event.data.get('execution_id', self._current_task.task_id)
            error = event.data.get("error", "Unknown error")
            failed_step_index = event.data.get("failed_step_index")
            duration_ms = event.data.get("duration_ms", 0.0)
            intent = event.data.get("intent", self._current_task.intent)
            plan = event.data.get("plan")
            step_results = event.data.get("step_results", [])
            context = event.data.get("context")

            self._current_task.task_id = execution_id
            self._current_task.completed_at = datetime.now()
            self._current_task.success = False
            self._current_task.error = error

            self._task_history.append(self._current_task)

            while len(self._task_history) > self._max_task_history:
                self._task_history.pop(0)

            failed_task = self._current_task
            self._current_task = None

            if self._conversation_history:
                for turn in reversed(self._conversation_history):
                    if turn.task_id == failed_task.task_id or turn.task_id == execution_id:
                        turn.success = False
                        turn.task_id = execution_id
                        break

            self._persist_completed_task(
                execution_id=execution_id,  
                intent=intent,
                plan=plan,
                success=False,
                duration_ms=duration_ms,
                step_results=step_results,
                context=context,
                failure_reason=error,
               failure_step_index=failed_step_index
            )

            emit(
                EventType.MEMORY_STORED,
                source="WorkingMemory",
               execution_id=execution_id,
               success=False,
               error=error
            )

            self._last_activity = datetime.now()

    def _persist_completed_task(
            self, 
            execution_id:str, 
            intent:Intent, 
            plan:Optional[Plan], 
            success:bool, 
            duration_ms:float, 
            step_results:List[Dict[str,Any]], 
            context:Optional[Dict[str,Any]], 
            failure_reason:Optional[str], 
            failure_step_index: Optional[int]
            )->int:
        pass