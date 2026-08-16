from typing import Optional, Dict, Any, List
from datetime import datetime
import time

from .events import EventType, Event, emit, subscribe
from ..action.executor import get_executor

from ..cognition.nlu.intent import extract_intent, get_intent_extractor
from ..cognition.planning.planner import generate_plan, get_planner, ReactPlanner
from ..cognition.observation import get_observation_builder
from ..perception.System.windows import WindowManager
from  .config import Observation

from ..core.config import ReactStep, get_config
from .task import Intent, Plan, Step

import json

_pipeline_active: bool = False
_processed_count: int = 0
_last_processed: Optional[str] = None

def _try_graph_bypass(text: str) -> bool:
    """
    Pre-flight: query Kùzu for a matching procedural macro.
    If confidence > threshold, skip the LLM entirely.
    Returns True if bypass fired, False to fall through.
    """
    # TODO (Micro-Planner): Remove synthetic Plan creation in
    # '_try_graph_bypass'. Update logic to push cached Action nodes
    # directly into the sequential execution queue.
    
    from ..memory.graph import find_matching_goal, get_procedure
    
    threshold = get_config().kuzu.bypass_confidence_threshold  # 0.92
    match = find_matching_goal(text, threshold)
    if not match:
        emit(EventType.MEMORY_PLAN_NOT_FOUND, source='Pipeline')
        return False
    
    actions = get_procedure(match['id'])
    if not actions:
        return False
    
    print(f"[Pipeline] Graph bypass: matched '{match['raw_command']}' "
          f"(confidence={match['confidence']:.2f})")
    
    steps = [
        Step(id=f"cached_{i}", action=a['tool_name'],
             parameters=json.loads(a.get('parameters_json') or '{}'),
             description=f"Cached: {a['tool_name']}")
        for i, a in enumerate(actions)
    ]
    plan = Plan(steps=steps, strategy="procedural_cache",
                reasoning=f"Graph bypass (conf={match['confidence']:.2f})")
    intent = Intent(action=match['action'], target=match['target'],
                    parameters={}, confidence=match['confidence'],
                    raw_command=text, complexity='cached')
    
    emit(EventType.MEMORY_PLAN_FOUND, source='Pipeline', plan=plan, intent=intent)
    emit(EventType.PLAN_CREATED, source='Pipeline', plan=plan, intent=intent)
    return True

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

    if get_config().kuzu.enable_graph_memory and _try_graph_bypass(text):
        return  # Executor handles via PLAN_CREATED

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

    print(f"[Pipeline] Intent: action={intent.action}, target={intent.target}, "
            f"confidence={intent.confidence:.2f}, complexity={intent.complexity}, "
            f"domain={getattr(intent, 'domain', 'unknown')}")

    # ── Step 2: Check confidence threshold ──
    if intent.action == "unknown":
        print(f"[Pipeline] Could not understand: \"{text}\"")

        return

    if intent.confidence < 0.3:
        print(f"[Pipeline] Confidence too low ({intent.confidence:.2f}), ignoring.")
        return


    _processed_count += 1
        
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

    complexity = getattr(intent, 'complexity', 'multi-step')

    if complexity == 'teaching':
        #[TODO] Implement teaching for Mei
        # _handle_teaching(intent,text)
        pass

    elif complexity == 'simple':
        _execute_simple(intent)
    
    else:
        _execute_loop(intent)
    # ── Step 4: Emit PLAN_CREATED → Executor picks it up ──
    emit(
        EventType.PLAN_CREATED,
        source='Pipeline',
        plan=plan,
        intent=intent
    )

def _execute_simple(intent: Intent) -> None:
    """Execution for simple actions,\n
       Falls back to ReAct if fails"""
    executor = get_executor()
    action_name = intent.action

    if not action_name:
        print(f"[Pipeline] No direct mapping simple intent: {intent.action}")
        _execute_loop(intent)
        return

    result = executor.execute_single_action(action=action_name,parameters=intent.parameters)

    if result.success:
        print("Action completed")
        emit(EventType.PLAN_COMPLETED, source='Pipeline',
             intent=intent, step_completed = 1, duration_ms = 0)
    
    else:
        print(f"Failed execution")
        _execute_loop(intent)

    
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

def _execute_loop(intent: Intent) -> None:
    """Run the full ReAct loop for a given input."""

    planner = get_planner()
    executor = get_executor()
    obs_builder = get_observation_builder()

    context = planner._gather_context(intent)
    history: List[ReactStep] = []
    start_time = time.time()

    print(f"[Pipeline] Starting ReAct loop for: {intent.action} → {intent.target}")

    for step_num in range(ReactPlanner.MAX_STEPS):

        # ── Thought: ask planner for the next step ──
        step = planner.next_step(intent, context, history)

        if step is None:
            elapsed = (time.time() - start_time) * 1000
            print(f"[Pipeline] Planner returned None at step {step_num + 1}.")
            emit(EventType.PLAN_FAILED, source='Pipeline',
                 intent=intent, reason="Planner returned no step",
                 duration_ms=elapsed)
            return

        print(f"[Pipeline] Step {step_num + 1} | Thought: {getattr(step, 'thought', '-')}")

        # ── Done signal ──
        if step.done:
            elapsed = (time.time() - start_time) * 1000
            print(f"Pipeline ReAct loop complete in {step_num + 1} step(s) "
                  f"({elapsed:.0f}ms)")
            emit(EventType.PLAN_COMPLETED, source='Pipeline',
                 intent=intent, steps_completed=len(history),
                 duration_ms=elapsed)
            return

        # ── Action: execute ──
        print(f"[Pipeline] Step {step_num + 1} | Action: {step.action} "
              f"params={step.parameters}")
        result = executor.execute_single_action(step.action, step.parameters)

        # ── Optional verification ──
        verify_result = None
        handler = executor.get_tool(step.action)
        if handler and handler.supports_verification:
            try:
                exec_ctx = executor._current_context
                verify_result = handler.verify_fn(
                    step.parameters, exec_ctx, result
                )
            except Exception as ve:
                print(f"[Pipeline] Verification error: {ve}")

        # ── Observation: build and attach ──
        observation = obs_builder.build(
            action=step.action,
            parameters=step.parameters,
            result=result,
            verify_result=verify_result,
            target_app=step.parameters.get('query') or intent.target
        )
        step.observation = observation
        history.append(step)

        status = "SUCCESS" if observation.success else "FAIL"
        print(f"Pipeline Step {step_num + 1} | Observation: {status} "
              f"window=({observation.foreground_window})")

        # ── Gather fresh context for next step ──
        context = planner._gather_context(intent)

        # ── Early abort: too many consecutive failures ──
        recent_failures = sum(
            1 for s in history[-3:] if not s.observation.success
        )
        if recent_failures >= 3:
            elapsed = (time.time() - start_time) * 1000
            emit(EventType.PLAN_FAILED, source='Pipeline',
                 intent=intent,
                 reason="3 consecutive failures — aborting loop",
                 duration_ms=elapsed)
            return

    # ── Max steps exceeded ──
    elapsed = (time.time() - start_time) * 1000
    emit(EventType.PLAN_FAILED, source='Pipeline',
         intent=intent,
         reason=f"Exceeded {ReactPlanner.MAX_STEPS} steps",
         duration_ms=elapsed)

"""def _execute_loop(intent:Intent)-> None:
    planner = get_planner()
    executor = get_executor()
    obs_builder = get_observation_builder()

    context = planner._gather_context(intent)
    history: List[ReactStep] = []
    start_time = time.time()

    for step_num in range(ReactPlanner.MAX_STEPS):
        # planner' sinput for the next step
        step = planner.next_step(intent, context, history)

        if step is None:
            emit(EventType.PLAN_FAILED, source="Pipeline",
                 intent= intent, reason="Planner returned no step")
            return
        
        if step.done:
            elapsed = (time.time() - start_time)* 1000
            emit(EventType.PLAN_COMPLETED, source="Pipeline",
                 intent= intent, steps_completed=len(history),
                 duration_ms=elapsed)
            return
        
        # Execute the step
        result = executor.execute_single_action(
            step.action, step.parameters
        )

        # Get verify result
        verify_result = None
        handler = executor.get_tool(step.action)
        if handler and handler.supports_verification:
            try:
                exec_context = executor._current_context
                verify_result = handler.verify_fn(
                    step.parameters, exec_context, result
                )
            except:
                pass
        
        observation = obs_builder.build(
            action=step.action,
            parameters=step.parameters,
            result=result,
            verify_result=verify_result,
            target_app=step.parameters.get('query') 
        )
        step.observation = observation

        history.append(step)

        print(f"Step {step_num + 1}: {step.action} ->"
              f"{'SUCCESS' if observation.success else 'FAIL'}"
              f"({observation.foreground_window})")
        
        context = planner._gather_context(intent)
    
    elapsed = (time.time() - start_time) * 1000
    emit(EventType.PLAN_FAILED, source="Pipeline",
         intent= intent,
         reason=f"Exceeded { ReactPlanner.MAX_STEPS} steps",
         duration_ms = elapsed)
    
"""
"""        step = planner.next_step(intent, context, history)
        
        if step is None:
            emit(EventType.PLAN_FAILED, source= "Pipeline",
                 intent= intent, reason= "Planner returned no step")
            return
        
        if step.done:
            emit(event_type=EventType.PLAN_COMPLETED, source= "Pipeline",
                 intent=intent, steps_completed=len(history))
            return
        
        result = executor.execute_single_action(
            step.action, step.parameters
        )

        try:
            fg = WindowManager().get_foreground_window()
            fg_title = fg.title[:50] if fg else None
            fg_process = fg.process_name if fg else None
        except:
            fg_title, fg_process = None, None
        
        observation = Observation(
            action=step.action,
            parameters=step.parameters,
            success=result.success,
            result_data=result.data or {},
            error=result.error,
            foreground_window=fg_title,
            foreground_process=fg_process,
        )
        step.observation = observation

        history.append(step)

        #[TODO]logging function implement here
        # _log_turn(intent,step,step_num)

        context = planner._gather_context(intent)
    
    emit(EventType.PLAN_FAILED, source="Pipeline",
         intent=intent, reason=f"Exceeded {ReactPlanner.MAX_STEPS} steps")
"""
#[TODO] subscribe to appropriate functions for ReAct loop

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