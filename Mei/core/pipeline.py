from typing import Optional, Dict, Any
from datetime import datetime

from .events import EventType, Event, emit, subscribe
from ..cognition.nlu.intent import extract_intent, get_intent_extractor
from ..cognition.planning.planner import generate_plan, get_planner, TaskPlanner
from .task import Intent, Plan
_pipeline_active: bool = False
_processed_count: int = 0
_last_processed: Optional[str] = None


def _on_transcription_complete(event: Event) -> None:
    """
    Called when speech is transcribed to text.
    This is the entry point of the entire pipeline.
    """
    global _processed_count, _last_processed

    if not _pipeline_active:
        return

    # Extract text from event
    text = None
    if hasattr(event, 'data') and isinstance(event.data, dict):
        text = event.data.get('text', '').strip()
    
    if not text:
        return

    # Avoid processing duplicate consecutive transcriptions
    if text == _last_processed:
        return
    _last_processed = text

    print(f"\n{'='*50}")
    print(f"[Pipeline] Received: \"{text}\"")
    print(f"{'='*50}")

    # ── Step 1: Parse Intent ──
    try:
        intent = extract_intent(text)
    except Exception as e:
        print(f"[Pipeline] Intent parsing failed: {e}")
        emit(
            EventType.ERROR,
            source='Pipeline',
            stage='intent_parsing',
            error=str(e),
            raw_text=text
        )
        return

    print(f"[Pipeline] Intent: action={intent.action}, target={intent.target}, confidence={intent.confidence:.2f}")

    # ── Step 2: Check confidence threshold ──
    if intent.action == "unknown":
        print(f"[Pipeline] Could not understand: \"{text}\"")
        return

    if intent.confidence < 0.3:
        print(f"[Pipeline] Confidence too low ({intent.confidence:.2f}), ignoring.")
        return

        # ── Step 3: Generate Plan ──
    try:
        plan = generate_plan(intent)
    except Exception as e:
        print(f"[Pipeline] Plan generation failed: {e}")
        emit(
            EventType.ERROR,
            source='Pipeline',
            stage='plan_generation',
            error=str(e),
            intent=intent
        )
        return

    if not plan or not plan.steps:
        print(f"[Pipeline] No plan generated for: {intent.action} → {intent.target}")
        print(f"[Pipeline] Strategy: {plan.strategy}")
        return

    print(f"[Pipeline] Plan created: {len(plan.steps)} steps, strategy={plan.strategy}")
    for i, step in enumerate(plan.steps):
        print(f"  Step {i+1}: {step.action} → {step.parameters}")

    _processed_count += 1

    # ── Step 4: Emit PLAN_CREATED → Executor picks it up ──
    emit(
        EventType.PLAN_CREATED,
        source='Pipeline',
        plan=plan,
        intent=intent
    )


def _on_plan_completed(event: Event) -> None:
    """Called when executor finishes a plan successfully."""
    data = event.data if hasattr(event, 'data') and isinstance(event.data, dict) else {}
    
    intent = data.get('intent')
    duration = data.get('duration_ms', 0)

    target = intent.target if intent else 'unknown'
    action = intent.action if intent else 'unknown'

    print(f"\n[Pipeline] ✓ Completed: {action} → {target} ({duration:.0f}ms)")

def _on_plan_failed(event: Event) -> None:
    """Called when executor fails a plan."""
    data = event.data if hasattr(event, 'data') and isinstance(event.data, dict) else {}

    intent = data.get('intent')
    error = data.get('error', 'Unknown error')
    duration = data.get('duration_ms', 0)

    target = intent.target if intent else 'unknown'
    action = intent.action if intent else 'unknown'

    print(f"\n[Pipeline] ✗ Failed: {action} → {target} — {error} ({duration:.0f}ms)")



def start_pipeline() -> None:
    """Subscribe to events and start the pipeline."""
    global _pipeline_active, _processed_count, _last_processed

    if _pipeline_active:
        print("[Pipeline] Already running.")
        return

    subscribe(EventType.TRANSCRIBE_COMPLETED, _on_transcription_complete)
    subscribe(EventType.PLAN_COMPLETED, _on_plan_completed)
    subscribe(EventType.PLAN_FAILED, _on_plan_failed)

    _pipeline_active = True
    _processed_count = 0
    _last_processed = None

    print("[Pipeline] Started: Transcription → Intent → Plan → Execute")


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
        'planner': get_planner() is not None,
    }


def process_text(text: str) -> None:
    """
    Manually push text through the pipeline.
    Useful for testing without voice input.
    
    Usage:
        from Mei.core.pipeline import process_text
        process_text("open chrome")
    """
    if not _pipeline_active:
        print("[Pipeline] Not active. Call start_pipeline() first.")
        return

    # Create a fake event
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
]


# ── Quick test ──
if __name__ == "__main__":
    from .events import Event

    # Initialize systems
    start_pipeline()

    # Get executor running
    from ..action.executor import get_executor
    executor = get_executor()

    # Test with manual text
    test_commands = [
        "open chrome",
        "open notepad",
        "close chrome",
        "type hello world",
        "press enter",
        "scroll down",
        "copy",
    ]

    for cmd in test_commands:
        print(f"\n\n{'#'*60}")
        print(f"Testing: \"{cmd}\"")
        print(f"{'#'*60}")
        process_text(cmd)

    stop_pipeline()