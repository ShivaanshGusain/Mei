from .config import get_config,ErrorRecord
from ..memory.store import get_memory_store
from .state import get_state_machine
from ..memory.working import get_working_memory
from ..perception.audio.listener import AudioListener
from ..perception.audio.transcriber import Transcriber
from ..cognition.planning.planner import get_planner
from ..cognition.nlu.intent import get_intent_extractor
from ..action import get_executor
from .events import emit, EventType,Event
from .state import AgentState

import time
from datetime import datetime, timedelta
from typing import List, Dict, Any
class MeiAgent:
    
    def start(self):
        """Start the agent."""
        print("🤖 Initializing Mei Agent...")
        
        # 1. Load config
        self._config = get_config()
        
        # 2. Initialize storage
        self._store = get_memory_store()
        
        # 3. Initialize state machine
        self._state_machine = get_state_machine()
        
        # 4. Initialize memory
        self._working_memory = get_working_memory()
        
        # 5. Initialize perception
        self._audio_listener = AudioListener()
        self._transcriber = Transcriber()
        
        # 6. Initialize cognition
        self._intent_extractor = get_intent_extractor()
        self._planner = get_planner()
        
        # 7. Initialize action
        self._executor = get_executor()
        
        # 8. Initialize error tracker
        self._error_tracker = ErrorTracker()
        
        # 9. Subscribe to events
        self._subscribe_to_events()
        
        # 10. Emit AGENT_STARTED
        emit(EventType.AGENT_STARTED, source="MeiAgent")
        
        # 11. Start audio
        self._audio_listener.start()
        self._transcriber.start()
        
        print("✅ Mei is listening (wake word: 'Mei')...")
        print("   Say 'Mei sleep' to stop")
        print("   Say 'Mei summarize' for session stats")
        
        # 12. Enter main loop
        self._running = True
        self._main_loop()



    def _main_loop(self):
        """Main event processing loop."""
        try:
            while self._running:
                time.sleep(0.1)  # Idle loop, events handled by subscribers
                
                # Check for critical errors
                if self._error_tracker.get_critical_count() > 10:
                    print("⚠️  Too many critical errors, entering safe mode")
                    self._state_machine.set_state(AgentState.ERROR)
                    time.sleep(5)
                    self._error_tracker.clear_critical()
                
        except KeyboardInterrupt:
            print("\n🛑 Keyboard interrupt received")
            self.stop()
        except Exception as e:
            print(f"❌ Fatal error in main loop: {e}")
            self.stop()

    def _on_transcribe(self, event: Event) -> None:
        text = event.data.get("text", "").lower().strip()
        
        # Sleep command
        if any(phrase in text for phrase in ["mei sleep", "stop listening", "goodbye mei"]):
            print("💤 Sleep command received")
            self.stop()
            return
        
        # Summarize command
        if any(phrase in text for phrase in ["summarize", "summary", "stats", "status"]):
            if "status" in text:
                summary = self._get_status()
            else:
                summary = self._get_summary()
            print(summary)
            # Don't process this as a normal command
            # Optionally: emit a special event so it doesn't go to intent extraction
            return
        
        # Help command
        if "help" in text and "mei" in text:
            self._print_help()
            return
        
        # If not special, let normal processing continue

    def _get_summary(self) -> str:
        """Generate session summary."""
        if not self._working_memory.is_active:
            return "No active session"
        
        wm = self._working_memory
        
        # Build summary
        lines = []
        lines.append("\n" + "="*60)
        lines.append("SESSION SUMMARY")
        lines.append("="*60)
        
        # Duration
        duration_sec = wm.session_duration_seconds
        hours = int(duration_sec // 3600)
        minutes = int((duration_sec % 3600) // 60)
        lines.append(f"Duration: {hours}h {minutes}m")
        
        # Task counts
        total = wm.total_tasks_count
        success = wm.tasks_completed_count
        failed = wm.tasks_failed_count
        if total > 0:
            success_pct = (success / total) * 100
            lines.append(f"Commands Processed: {total}")
            lines.append(f"Successes: {success} ({success_pct:.0f}%)")
            lines.append(f"Failures: {failed} ({100-success_pct:.0f}%)")
        else:
            lines.append("No commands processed yet")
        
        # Learning stats
        lines.append("\nLEARNED THIS SESSION:")
        
        # Query store for counts
        with self._store.transaction() as conn:
            cursor = conn.cursor()
            
            # Plans cached
            cursor.execute("SELECT COUNT(*) FROM plan_cache WHERE last_used_at >= ?", 
                        (wm._started_at.isoformat(),))
            plan_count = cursor.fetchone()[0]
            lines.append(f"  - Cached {plan_count} plans")
            
            # Elements cached
            cursor.execute("SELECT COUNT(*) FROM element_cache WHERE last_hit >= ?",
                        (wm._started_at.isoformat(),))
            elem_count = cursor.fetchone()[0]
            lines.append(f"  - Cached {elem_count} element positions")
        
        # Recent errors
        if self._error_tracker.recent_errors:
            lines.append("\nRECENT ERRORS:")
            error_summary = self._error_tracker.get_error_summary()
            lines.append(error_summary)
        
        lines.append("="*60)
        return "\n".join(lines)


    def _get_status(self) -> str:
        """Generate current status."""
        lines = []
        lines.append("\n" + "="*60)
        lines.append("AGENT STATUS")
        lines.append("="*60)
        
        # State
        state = self._state_machine.get_state()
        lines.append(f"State: {state.name}")
        
        # Session info
        if self._working_memory.is_active:
            duration = self._working_memory.session_duration_seconds
            minutes = int(duration // 60)
            lines.append(f"Session: {minutes}m")
        else:
            lines.append("Session: Not active")
        
        # Last command
        recent = self._working_memory.get_recent_conversation(1)
        if recent:
            last = recent[0]
            elapsed = (datetime.now() - last.timestamp).seconds
            lines.append(f"Last Command: \"{last.user_input}\" ({elapsed}s ago)")
        
        # Current task
        current = self._working_memory.get_current_task()
        if current:
            lines.append(f"Current Task: {current.intent.action} → {current.intent.target}")
        else:
            lines.append("Current Task: None")
        
        # Memory stats
        with self._store.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM plan_cache WHERE is_valid=1")
            plans = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM element_cache WHERE is_valid=1")
            elements = cursor.fetchone()[0]
        
        lines.append(f"\nMEMORY:")
        lines.append(f"  - Cached Plans: {plans}")
        lines.append(f"  - Cached Elements: {elements}")
        
        if state == AgentState.IDLE:
            lines.append("\nREADY FOR NEXT COMMAND")
        
        lines.append("="*60)
        return "\n".join(lines)
    
    def stop(self):
        """Graceful shutdown."""
        print("\n🛑 Shutting down Mei Agent...")
        
        self._running = False
        
        # 1. Stop audio first
        if self._audio_listener:
            self._audio_listener.stop()
        if self._transcriber:
            self._transcriber.stop()
        
        # 2. Emit AGENT_STOPPED (triggers WorkingMemory cleanup)
        emit(EventType.AGENT_STOPPED, source="MeiAgent")
        
        # 3. Wait for event processing
        time.sleep(0.5)
        
        # 4. Show final summary
        if self._working_memory and self._working_memory.is_active:
            summary = self._get_summary()
            print(summary)
        
        # 5. Cleanup
        self._cleanup()
        
        print("✅ Mei Agent stopped")


    def _cleanup(self):
        """Release resources."""
        # Close database connections
        if self._store:
            self._store.close_connection()
        
        # Clear references
        self._audio_listener = None
        self._transcriber = None
        self._intent_extractor = None
        self._planner = None
        self._executor = None
        self._working_memory = None









class ErrorTracker:
    def __init__(self, max_recent=100):
        self.recent_errors: List[ErrorRecord] = []
        self.error_counts: Dict[str, int] = {}
        self.max_recent = max_recent
    
    def add_error(self, error: str, context: Dict[str, Any], severity: str = "transient"):
        record = ErrorRecord(
            timestamp=datetime.now(),
            error_type=self._classify_error(error),
            error_message=error,
            context=context,
            severity=severity
        )
        
        self.recent_errors.append(record)
        if len(self.recent_errors) > self.max_recent:
            self.recent_errors.pop(0)
        
        # Count
        error_type = record.error_type
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
    
    def _classify_error(self, error: str) -> str:
        """Classify error into type."""
        error_lower = error.lower()
        
        if "not found" in error_lower:
            return "element_not_found"
        elif "timeout" in error_lower:
            return "timeout"
        elif "failed to launch" in error_lower:
            return "app_launch_failure"
        elif "exception" in error_lower:
            return "exception"
        else:
            return "other"
    
    def get_error_summary(self) -> str:
        """Get summary of recent errors."""
        if not self.recent_errors:
            return "  No recent errors"
        
        # Get top 5 most common
        sorted_errors = sorted(self.error_counts.items(), key=lambda x: x[1], reverse=True)
        lines = []
        for error_type, count in sorted_errors[:5]:
            # Get most recent example
            for record in reversed(self.recent_errors):
                if record.error_type == error_type:
                    lines.append(f"  - \"{record.error_message}\" ({count} times)")
                    break
        return "\n".join(lines)
    
    def get_critical_count(self) -> int:
        """Get count of critical errors in last minute."""
        one_min_ago = datetime.now() - timedelta(minutes=1)
        return sum(1 for e in self.recent_errors 
                  if e.severity == "critical" and e.timestamp > one_min_ago)
    
    def clear_critical(self):
        """Clear critical errors (after recovery)."""
        self.recent_errors = [e for e in self.recent_errors if e.severity != "critical"]



