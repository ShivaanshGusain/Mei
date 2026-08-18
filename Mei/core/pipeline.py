from typing import Optional, Dict, Any, List
from datetime import datetime
import time
import json

from .events import EventType, Event, emit, subscribe
from ..action.executor import get_executor
from ..action.context import ExecutionContext

from ..cognition.intent import extract_intent, get_intent_extractor
from ..cognition.planning.microplanner import get_microplanner
from ..cognition.observation import get_observation_builder
from ..perception.System.windows import WindowManager
from .config import Observation, get_config
from .task import Intent, IntentSequence, StepExecutionStatus, IntentStep

from ..memory.graph import find_matching_goal, get_procedure

_pipeline_active: bool = False
_processed_count: int = 0
_last_processed: Optional[str] = None


def process_user_command(text: str, context: ExecutionContext) -> bool:
    extractor = get_intent_extractor()
    planner = get_microplanner()
    
    # ── Phase 1: Memory Pre-Flight ──
    sequence = None
    if getattr(get_config(), "kuzu", None) and get_config().kuzu.enable_graph_memory:
        candidate = find_matching_goal(text, get_config().kuzu.bypass_confidence_threshold)
        print(f"[Pipeline] Memory lookup: candidate={candidate}")
        if candidate:
            actions = get_procedure(candidate["id"])
            print(f"[Pipeline] Procedure actions: {len(actions)} steps — {actions}")
            if actions:
                emit(EventType.MEMORY_PLAN_FOUND, source="Pipeline", confidence=candidate.get("confidence", 1.0))
                # ── Phase 2a: Intent Verifies the macro ──
                sequence = extractor.verify_macro(text, candidate, actions)

    if sequence is None:
        emit(EventType.MEMORY_PLAN_NOT_FOUND, source="Pipeline")
        # ── Phase 2b: Intent Decomposes fresh command ──
        sequence = extractor.decompose(text)

    if not sequence or not sequence.steps:
        print(f"[Pipeline] Could not decompose: '{text}'")
        return False

    # ── Phase 3: Micro-Planner Sequential Loop ──
    print(f"[Pipeline] Starting execution loop for: {text}")
    return planner.execute_sequence(sequence, context)


def _on_transcription_complete(event: Event) -> None:
    """
    Called when speech is transcribed to text.
    """
    global _processed_count, _last_processed

    if not _pipeline_active:
        return

    text = None
    if hasattr(event, 'data') and isinstance(event.data, dict):
        text = event.data.get('text', '').strip()
    
    if not text:
        return

    if text == _last_processed:
        return
    _last_processed = text

    print(f"\n{'='*50}")
    print(f"[Pipeline] Received: \"{text}\"")
    print(f"{'='*50}")

    executor = get_executor()
    context = getattr(executor, '_current_context', None)
    if not context:
        context = ExecutionContext.empty()
        from ..memory.working import get_working_memory
        session_id = get_working_memory()._session_id
        if session_id:
            context.set_variable("session_id", session_id)
        
    process_user_command(text, context)
    _processed_count += 1


def start_pipeline() -> None:
    """Subscribe to events and start the pipeline."""
    global _pipeline_active, _processed_count, _last_processed

    import threading
    def _preload():
        get_intent_extractor()._llm.preload()
        get_microplanner()._llm.preload()
        print("[Pipeline] Models preloaded and ready.")
    threading.Thread(target=_preload, daemon=True).start()

    subscribe(EventType.TRANSCRIBE_COMPLETED, _on_transcription_complete)
    _pipeline_active = True
    if _pipeline_active:
        print("[Pipeline] Already running.")
        return

    subscribe(EventType.TRANSCRIBE_COMPLETED, _on_transcription_complete)
    
    _pipeline_active = True
    _processed_count = 0
    _last_processed = None

    print("[Pipeline] Started: Transcription → Intent → MicroPlanner → Execute")


def stop_pipeline() -> None:
    """Stop processing new transcriptions."""
    global _pipeline_active
    _pipeline_active = False
    print(f"[Pipeline] Stopped. Processed {_processed_count} commands this session.")


def get_pipeline_status() -> Dict[str, Any]:
    """Return pipeline health info."""
    return {
        'active': _pipeline_active,
        'processed_count': _processed_count,
        'last_processed': _last_processed,
        'intent_parser': get_intent_extractor() is not None,
        'planner': get_microplanner() is not None,
    }


def process_text(text: str) -> None:
    if not _pipeline_active:
        print("[Pipeline] Not active. Call start_pipeline() first.")
        return

    event = Event(
        type=EventType.TRANSCRIBE_COMPLETED,
        source='manual',
        data={'text': text}
    )
    _on_transcription_complete(event)


__all__ = [
    'start_pipeline',
    'stop_pipeline',
    'get_pipeline_status',
    'process_text',
    'process_user_command',
]