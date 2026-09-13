from typing import Optional, Dict, Any, List
from datetime import datetime
import time
import json

from .events import EventType, Event, emit, subscribe
from ..action.executor import get_executor
from ..action.context import ExecutionContext

from ..cognition.intent import get_intent_extractor
from ..cognition.planning.microplanner import get_microplanner
from ..cognition.planning.evaluator import verify_step
from ..perception.System.windows import WindowManager
from .config import get_config
from .task import IntentSequence, StepExecutionStatus, IntentStep
from .cancellation import get_cancellation_token

from ..memory.graph import find_matching_goal, get_procedure

_pipeline_active: bool = False
_processed_count: int = 0
_last_processed: Optional[str] = None

# ── Gatekeeping thresholds ────────────────────────────────────────────────────
TIER1_CONFIDENCE: float = 0.95
TIER1_STABILITY:  float = 0.75
TIER2_CONFIDENCE: float = 0.80
TIER2_STABILITY:  float = 0.50


def _get_tier(confidence: float, stability: float) -> int:
    """
    Gatekeeping matrix:

    Gate 1 (Intent Match): confidence — how well the command matches stored memory.
    Gate 2 (Volatility):   stability  — how safe it is to replay the sequence blind.

    Tier 1: confidence ≥ 0.95 AND stability ≥ 0.75  → full bypass, direct execution
    Tier 2: confidence ≥ 0.80 OR  stability ≥ 0.50  → skip intent LLM, planner executes
    Tier 3: everything else                          → full decompose (intent + planner)
    """
    if confidence >= TIER1_CONFIDENCE and stability >= TIER1_STABILITY:
        return 1
    if confidence >= TIER2_CONFIDENCE or stability >= TIER2_STABILITY:
        return 2
    return 3


def _actions_to_intent_steps(actions: list) -> List[IntentStep]:
    """Convert stored Action dicts (from get_procedure) to IntentStep objects."""
    steps = []
    for i, a in enumerate(actions):
        try:
            params = json.loads(a.get("parameters_json", "{}") or "{}")
        except (json.JSONDecodeError, TypeError):
            params = {}

        steps.append(IntentStep(
            step_id=i + 1,
            description=a.get("step_description") or a.get("tool_name", "unknown"),
            expected_output=a.get("step_expected_output") or "",
            domain=a.get("step_domain") or "unknown",
            target=None,
            parameters=params,
        ))
    return steps


def process_user_command(text: str, context: ExecutionContext) -> bool:
    success = _do_process_user_command(text, context)
    if success:
        from ..core.events import emit, EventType
        emit(EventType.PLAN_COMPLETED, source="Pipeline",
             execution_id=context.get_variable("execution_id", ""),
             duration_ms=context.elapsed_time_ms() if hasattr(context, "elapsed_time_ms") else 0.0,
             success=True)
    return success

def _do_process_user_command(text: str, context: ExecutionContext) -> bool:
    extractor = get_intent_extractor()
    planner   = get_microplanner()
    executor  = get_executor()

    if not (getattr(get_config(), "kuzu", None) and get_config().kuzu.enable_graph_memory):
        # Graph memory disabled — always decompose
        sequence = extractor.decompose(text)
        if not sequence or not sequence.steps:
            print(f"[Pipeline] Could not decompose: '{text}'")
            return False
        print(f"[Pipeline] Starting execution loop for: {text}")
        return planner.execute_sequence(sequence, context)

    # ── Phase 1: Memory pre-flight ────────────────────────────────────────────
    candidate = find_matching_goal(text, get_config().kuzu.bypass_confidence_threshold)
    print(f"[Pipeline] Memory lookup: candidate={candidate}")

    if candidate:
        context.set_variable("matched_goal_id", candidate["id"])
        actions    = get_procedure(candidate["id"])
        confidence = float(candidate.get("confidence", 0.0))
        stability  = float(candidate.get("stability_score") or 0.5)
        tier       = _get_tier(confidence, stability)

        print(f"[Pipeline] Memory: confidence={confidence:.4f}, "
              f"stability={stability:.3f} -> TIER {tier}")

        if actions:
            # ── TIER 1: Full bypass — direct execution, no LLM calls ─────────
            if tier == 1:
                emit(EventType.MEMORY_PLAN_FOUND, source="Pipeline",
                     confidence=confidence, tier=1)
                print(f"[Pipeline] TIER 1 — executing {len(actions)} stored step(s) directly.")

                intent_steps = _actions_to_intent_steps(actions)
                succeeded    = []   # list of (tool_name, params, result)

                for i, (action, intent_step) in enumerate(zip(actions, intent_steps)):
                    tool_name = action.get("tool_name", "")
                    try:
                        params = json.loads(action.get("parameters_json", "{}") or "{}")
                    except (json.JSONDecodeError, TypeError):
                        params = {}

                    print(f"[Pipeline] Tier1 step {i+1}/{len(actions)}: "
                          f"{tool_name}({params})")

                    # Cancellation check before each direct execution
                    if get_cancellation_token().is_cancelled:
                        emit(EventType.PLAN_FAILED, source="Pipeline", reason="cancelled")
                        return False

                    result = executor.execute_single_action(tool_name, params, context)
                    is_ok, reason = verify_step(intent_step, result, context)

                    if result.success and is_ok:
                        succeeded.append((tool_name, params, result))

                        # Keep context current for env_state injection
                        completed = context.get_variable("completed_steps", [])
                        completed.append(f"{tool_name}({params})")
                        context.set_variable("completed_steps", completed)
                        if context.current_window:
                            context.set_variable("current_window_title",
                                                  context.current_window.title)
                    else:
                        # Self-heal: hand failed step + remaining to planner
                        print(f"[Pipeline] Tier 1 step {i+1} failed "
                              f"({reason}). Triggering self-heal.")
                        remaining = intent_steps[i:]  # include the failed step
                        return planner.heal_from_failure(
                            succeeded_steps=succeeded,
                            failed_step_index=i,
                            failed_tool=tool_name,
                            failed_params=params,
                            failure_reason=reason,
                            remaining_intent_steps=remaining,
                            original_command=text,
                            context=context,
                        )

                # All steps executed successfully — commit episode
                step_records = [
                    {
                        "action":               tool,
                        "parameters":           params,
                        "success":              True,
                        "duration_ms":          0,
                        "data":                 r.data,
                        "method_used":          r.method_used or "direct",
                        "step_description":     s.description,
                        "step_domain":          s.domain,
                        "step_expected_output": s.expected_output,
                    }
                    for (tool, params, r), s in zip(succeeded, intent_steps)
                ]
                planner._commit_to_graph(
                    IntentSequence(
                        raw_command=text,
                        steps=intent_steps,
                        is_verified_macro=True,
                        source_goal_id=candidate["id"],
                        confidence=confidence,
                    ),
                    step_records,
                    0,
                    context,
                )
                return True

            # ── TIER 2: Skip intent LLM, planner regenerates tool calls ──────
            elif tier == 2:
                emit(EventType.MEMORY_PLAN_FOUND, source="Pipeline",
                     confidence=confidence, tier=2)
                print(f"[Pipeline] TIER 2 — skipping intent LLM, "
                      f"planner executes {len(actions)} stored step(s).")
                intent_steps = _actions_to_intent_steps(actions)
                sequence = IntentSequence(
                    raw_command=text,
                    steps=intent_steps,
                    is_verified_macro=True,
                    source_goal_id=candidate["id"],
                    confidence=confidence,
                )
                print(f"[Pipeline] Starting execution loop for: {text}")
                return planner.execute_sequence(sequence, context)

            # ── TIER 3 from memory: verify_macro then planner ─────────────────
            else:
                emit(EventType.MEMORY_PLAN_FOUND, source="Pipeline",
                     confidence=confidence, tier=3)
                print(f"[Pipeline] TIER 3 (memory) — running verify_macro.")
                sequence = extractor.verify_macro(text, candidate, actions)
                if sequence:
                    print(f"[Pipeline] Starting execution loop for: {text}")
                    return planner.execute_sequence(sequence, context)
                # verify_macro rejected — fall through to decompose
                print(f"[Pipeline] verify_macro rejected macro, decomposing fresh.")

    # ── Phase 2: No memory match or macro rejected — full decompose ───────────
    emit(EventType.MEMORY_PLAN_NOT_FOUND, source="Pipeline")
    sequence = extractor.decompose(text)

    if not sequence or not sequence.steps:
        print(f"[Pipeline] Could not decompose: '{text}'")
        return False

    print(f"[Pipeline] Starting execution loop for: {text}")
    return planner.execute_sequence(sequence, context)


def _on_transcription_complete(event: Event) -> None:
    """Called when speech is transcribed to text."""
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
    context  = getattr(executor, '_current_context', None)
    if not context:
        context = ExecutionContext.empty()
        from ..memory.working import get_working_memory
        session_id = get_working_memory()._session_id
        if session_id:
            context.set_variable("session_id", session_id)
        executor._current_context = context

    process_user_command(text, context)
    _processed_count += 1


def start_pipeline() -> None:
    """Subscribe to events and start the pipeline.
    
    Models are loaded lazily on first use. The GPU swap mechanism in
    engine.py ensures only one model occupies VRAM at a time, preventing
    OOM crashes on laptops with limited GPU memory.
    """
    global _pipeline_active, _processed_count, _last_processed

    if _pipeline_active:
        print("[Pipeline] Already running.")
        return

    subscribe(EventType.TRANSCRIBE_COMPLETED, _on_transcription_complete)

    _pipeline_active = True
    _processed_count = 0
    _last_processed  = None

    print("[Pipeline] Started: Transcription -> Intent -> MicroPlanner -> Execute")
    print("[Pipeline] Models will load on first use (GPU swap enabled).")


def stop_pipeline() -> None:
    """Stop processing new transcriptions."""
    global _pipeline_active
    _pipeline_active = False
    print(f"[Pipeline] Stopped. Processed {_processed_count} commands this session.")


def get_pipeline_status() -> Dict[str, Any]:
    """Return pipeline health info."""
    return {
        'active':          _pipeline_active,
        'processed_count': _processed_count,
        'last_processed':  _last_processed,
        'intent_parser':   get_intent_extractor() is not None,
        'planner':         get_microplanner() is not None,
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
