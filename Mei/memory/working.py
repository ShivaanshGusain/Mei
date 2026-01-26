import threading
import secrets
from typing import Dict, Any, Optional, List
from datetime import datetime

from ..core.config import ConversationTurn, SessionTask,UserCorrection
from ..core.task import Intent, Plan
from ..core.events import EventType, Event, subscribe, emit
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
        if auto_subscribe:
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
        
        intent_dict = {
            'action':intent.action,
            'target':intent.target,
            'parameters':intent.parameters,
            'confidence':intent.confidence
        }

        if plan is not None:
            plan_dict = {
                'strategy':plan.strategy if hasattr(plan,'strategy') else 'unknown',
                'reasoning': plan.reasoning if hasattr(plan,'reasoning') else "",
                'steps': []
            }

            if hasattr(plan,'steps'):
                for step in plan.steps:
                    if hasattr(step, 'to_dict'):
                        plan_dict['steps'].append(step.to_dict())
                    elif hasattr(step,"__dict__"):
                        plan_dict['steps'].append({
                            'action':step.action,
                            'parameters':step.parameters,
                            'description':getattr(step,'description',"")
                        })
        
        else:
            plan_dict = {"strategy":"unknown","reasoning":"","steps":[]}

        try:
            self._store.save_task_execution(
                execution_id=execution_id,
                session_id=self._session_id,
                raw_command=intent.raw_command,
                intent= intent_dict,
                plan = plan_dict,
                success= success,
                duration_ms=duration_ms,
                failure_reason=failure_reason,
                failure_step_index=failure_step_index,
                context= context,
                step_results = step_results
            )

        except Exception as e:
            print(f"Failed to save task execution: {e}")
            return
        
        if success and plan is not None:
            try:
                intent_pattern = self._build_intent_pattern(intent)
                self._store.cache_plan(
                    intent_pattern=intent_pattern,
                    intent_action=intent.action,
                    intent_target=intent.target,
                    plan_strategy=plan_dict['strategy'],
                    plan_steps=plan_dict['steps'],
                    normalized_command=intent.raw_command.lower().strip()
                )
            except Exception as e:
                print(f"Failed to cache plan: {e}")

        
        if not success:
            try:
                intent_pattern = self._build_intent_pattern(intent)
                self._store.record_plan_failure(intent_pattern)
            except Exception as e:
                print(f"Failed to record plan failure: {e}")

        try:
            self._store.record_command(
                raw_pattern=intent.raw_command,
                intent_action= intent.action,
                intent_target=intent.target,
                success=success,
                normalized_pattern=intent.raw_command.lower().strip()
            )
        
        except Exception as e:
            print(f"Failed to record command: {e}")

    def _build_intent_pattern(self, intent:Intent)->str:
        pattern = intent.action.lower()

        if intent.target:
            pattern += f":{intent.target.lower()}"

        variable_action = ['search', 'type','navigate']

        if intent.actoin.lower() in variable_action:
            pattern += ":*"

        return pattern
    
    def _on_agent_stopped(self,event:Event)->None:
        if not self._is_active:
            return
        
        with self._lock:

            if self._current_task is not None:

                self._current_task.completed_at = datetime. now()
                self._current_task.success = False
                self._current_task.error = "Session ended before task completion"
                self._task_history.append(self._current_task)
                self._current_task = None

            for key, value in self._session_preferences.items():
                try:
                    existing = self._store.get_preferences(key)
                    if existing!=value:
                        self._store.set_preference(
                            preference_key=key,
                            preference_value=value,
                            is_explicit=False,
                            confidence=0.5
                        )

                except Exception as e:
                    print(f"Failed to persist preference {key}: {e}")

            for correction in self._corrections:
                try:
                    key = f"correction:{correction.original_intent.target}:{correction.corrected_intent.target}"
                    self._store.set_preference(
                        preference_key=key,
                        preference_value=correction.to_dict(),
                        category='correction',
                        is_explicit=False,
                        confidence=0.7
                    )
                
                except Exception as e:
                    pass
            
        total_tasks = len(self._task_history)
        successful_tasks = sum(1 for t in self._task_history if t.success)
        failed_tasks = total_tasks- successful_tasks
        session_duration = (datetime.now() - self._started_at).total_seconds() if self._started_at else 0

        try:
            deleted = self._store.cleanup_old_data()
            if any(v > 0 for v in deleted.values()):
                print(f"Cleanup deleted {deleted}")
            
        except Exception as e:
            print(f"Cleanup Failed: {e}")

        emit(
            EventType.MEMORY_SESSION_ENDED,
            source='WorkingMemory',
            session_id = self._session_id,
            total_tasks = total_tasks,
            successful_tasks= successful_tasks,
            failed_tasks = failed_tasks,
            duration_seconds = session_duration,
            correction_recorded = len(self._corrections)
        )

        self._session_id = None
        self._started_at = None
        self._last_activity = None
        self._is_active = None
        self._conversation_history = []
        self._task_history = []
        self._current_task = None
        self._corrections = []
        self._session_preferences = {}
        self._prior_context = []

        print(f"Session ended. {successful_tasks}/{total_tasks} task succeeded. Duration: {session_duration:.1f}s")

    def get_context_for_planner(self, intent:Intent)-> Dict[str,Any]:
        context = {
                   'session_id':self._session_id,
                   'session_active' : self._is_active
                   }

        if len(self._conversation_history) >1:
            recent = self._conversation_history[-4:-1] if len(self._conversation_history)>=4 else self._conversation_history[-1]
            context['recent_conversation'] = [
                {
                    'user_input':turn.user_input,
                    'intent_aciton': turn.intent.action if turn.intent else None,
                    'intent_target':turn.intent.target if turn.intent else None,
                    'success': turn.success
                }
                for turn in recent
            ]

        related_tasks = []
        for task in self._task_history:
            if (task.intent.action == intent.action or task.intent.target == intent.target):
                related_tasks.append(task)

        if related_tasks:
            context['session_related_tasks'] = [
                {
                       "action": t.intent.action,
                       "target": t.intent.target,
                       "strategy": t.plan_strategy,
                       "success": t.success,
                       "error": t.error,
                       "from_cache": t.from_cache
                }
                for t in related_tasks[-3:]
            ]
        
        relevant_corrections = [
            c for c in self._corrections
            if (c.original_intent and (c.original_intent.action == intent.action or c.original_intent.target == intent.target))
        ]

        if relevant_corrections:
            context['user_corrections'] = [
                {
                       "original_target": c.original_intent.target if c.original_intent else None,
                       "corrected_target": c.corrected_intent.target if c.corrected_intent else None,
                       "note": f"User corrected '{c.original_input}' to '{c.corrected_input}'"      
                }
                for c in relevant_corrections[-3:]
            ]
        
        if self._session_preferences:
            relevant_prefs = {}
            
            if f"default_{intent.action}" in self._session_preferences:
                relevant_prefs[f"default_{intent.action}"] = self._session_preferences[f"default_{intent.action}"]

            if "default_browser" in self._session_preferences:
                relevant_prefs["default_browser"] = self._session_preferences["default_browser"]

            if relevant_prefs:
                context["preferences"] = relevant_prefs

        return context
    
    def get_recent_conversation(self, turns:int = 5)->List[ConversationTurn]:
        with self._lock:
            return self._conversation_history[-turns].copy()
        
    def get_conversation_summary_for_llm(self,max_turns:int = 5)->str:
        
        with self._lock:
            turns = self._conversation_history[-max_turns]
        
        if not turns:
            return "Noo previous conversation in this session."
        
        lines = ['Recent conversation:']

        for turn in turns:
            lines.append(f" User: \"{turn.user_input}\"")
            
            if turn.intent:
                lines.append(f" Intent: {turn.intent.action} target: {turn.intent.target}")

            if turn.success is not None:
                outcome = 'succeeded' if turn.success else 'failed'
                lines.append(f" Task {outcome}")
            
        return '\n'.join(lines)

    def get_task_history(self, count:int = 10)->List[SessionTask]:
        with self._lock:
            return self._task_history[-count].copy()
        
    def get_current_task(self)->Optional[SessionTask]:
        with self._lock:
            return self._current_task

    def add_agent_response(self, response:str)->None:
        with self._lock:
            if self._conversation_history:
                self._conversation_history[-1].agent_response = response

    def set_session_preference(self, key:str, value:Any)->None:
        with self._lock:
            self._session_preferences[key] = value
        
    def get_session_preference(self, key:str, default:Any = None) -> Any:
        return self._session_preferences.get(key, default)


    @property
    def session_id(self)->Optional[str]:
        return self._session_id

    @property
    def is_active(self)->bool:
        return self._is_active

    @property
    def session_duration_seconds(self)->float:
        if self._started_at is None:
            return 0.0
        
        return (datetime.now() - self._started_at).total_seconds()

    @property
    def tasks_completed_count(self)->int:
        return sum(1 for t in self._task_history if t.success)
    
    @property
    def task_failed_count(self)->int:
        return sum(1 for t in self._task_history if t.success is False)
    
    @property
    def total_tasks_count(self)->int:
        return len(self._task_history)
    
    def to_dict(self)->Dict[str,Any]:
        with self._lock:
            return {
                'session_id': self._session_id,
                "is_active": self._is_active,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "last_activity": self._last_activity.isoformat() if self._last_activity else None,
                "duration_seconds": self.session_duration_seconds,
                "conversation_turns": len(self._conversation_history),
                "tasks_completed": self.tasks_completed_count,
                'tasks_failed': self.task_failed_count,
                'corrections_recorded': len(self._corrections),
                'current_task_id': self._current_task.task_id if self._current_task else None,
                'preferences':self._session_preferences.copy()
            }
    
_working_memory_instance: Optional[WorkingMemory] = None

def get_working_memory()->WorkingMemory:

    global _working_memory_instance
    if _working_memory_instance is None:
        _working_memory_instance = WorkingMemory()

    return _working_memory_instance

__all__ = [
    'WorkingMemory',
    'get_working_memory',
    'ConversationTurn',
    'SessionTask',
]

if __name__ == "__main__":
    """Test the working memory module."""
    import time
    print("=" * 60)
    print("WORKING MEMORY TEST")
    print("=" * 60)
    
    # Create instance (without auto-subscribe for manual testing)
    wm = WorkingMemory(auto_subscribe=False)
    
    # Test 1: Session start
    print("\nTest 1: Session Start")
    wm._on_agent_started(Event(EventType.AGENT_STARTED, {}))
    time.sleep(1)
    print(f"  Session ID: {wm.session_id}")
    print(f"  Is Active: {wm.is_active}")
    
    # Test 2: Record transcription
    print("\nTest 2: Record Transcription")
    wm._on_transcribe_completed(Event(
        EventType.TRANSCRIBE_COMPLETED,
        {"text": "open chrome"}
    ))
    print(f"  Conversation turns: {len(wm._conversation_history)}")
    
    # Test 3: Record intent
    print("\nTest 3: Record Intent")
    test_intent = Intent(
        action="open",
        target="chrome",
        parameters={},
        confidence=0.9,
        raw_command="open chrome"
    )
    wm._on_intent_recognized(Event(
        EventType.INTENT_RECOGNIZED,
        {"intent": test_intent}
    ))
    print(f"  Last turn intent: {wm._conversation_history[-1].intent}")
    
    # Test 4: Build context
    print("\nTest 4: Build Planner Context")
    context = wm.get_context_for_planner(test_intent)
    print(f"  Context keys: {list(context.keys())}")
    
    # Test 5: Session end
    print("\nTest 5: Session End")
    print(f"  Is Active: {wm.is_active}")
    print(f"  Session ID: {wm.session_id}")
    wm._on_agent_stopped(Event(EventType.AGENT_STOPPED, {}))

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
