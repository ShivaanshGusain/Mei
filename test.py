import time
from datetime import datetime

from Mei.core.events import EventType, subscribe, emit, Event
from Mei.core.task import Intent, Plan, Step, StepStatus
from Mei.memory.store import get_memory_store
from Mei.memory.working import WorkingMemory, get_working_memory
from Mei.cognition.planning.planner import TaskPlanner, get_planner

# --- 1. SETUP HELPERS ---
# def clear_db():
#     """Wipe relevant tables for a clean test."""
#     store = get_memory_store()
#     with store.transaction() as conn:
#         # 1. Delete child records first to satisfy Foreign Key constraints
#         conn.execute("DELETE FROM step_executions")
        
#         # 2. Now delete parent records
#         conn.execute("DELETE FROM task_executions")
        
#         # 3. Clear other caches
#         conn.execute("DELETE FROM plan_cache")
#         conn.execute("DELETE FROM command_patterns")
        
#     print("Database cleared.")# --- 2. THE TEST ---
def run_test():
    print("=" * 60)
    print("ARCHITECTURE LEARNING LOOP TEST")
    print("=" * 60)

    # Clean start
    # clear_db()

    # Initialize Components
    store = get_memory_store()
    
    # Get singletons (important: use get_ functions for consistency)
    wm = get_working_memory()
    planner = get_planner(auto_subscribe=True)

    # CRITICAL: Start the session so WorkingMemory processes events
    print("\n--- PHASE 0: STARTING SESSION ---")
    emit(
        EventType.AGENT_STARTED,
        source="test"
    )
    time.sleep(0.2)
    
    if wm.is_active:
        print("SUCCESS: WorkingMemory session started")
        print(f"   Session ID: {wm.session_id}")
    else:
        print("FAIL: WorkingMemory session not started")
        return

    # Define a test intent
    test_intent = Intent(
        action="open",
        target="notepad",
        parameters={},
        confidence=1.0,
        raw_command="open notepad"
    )

    print("\n--- PHASE 1: SIMULATE PLAN CREATION ---")
    
    # Create a plan that would be generated
    dummy_plan = Plan(
        steps=[
            Step(
                id="s1",
                action="launch_app",
                parameters={"app_name": "notepad"},
                description="Launch Notepad",
                status=StepStatus.PENDING
            ),
            Step(
                id="s2",
                action="wait",
                parameters={"seconds": 1.5},
                description="Wait for app to load",
                status=StepStatus.PENDING
            )
        ],
        strategy="launch_app_direct",
        reasoning="Notepad is not running, launching it",
        created_at=datetime.now()
    )

    # Emit PLAN_CREATED to trigger WorkingMemory._on_plan_created
    # This sets up _current_task
    emit(
        EventType.PLAN_CREATED,
        source="test",
        plan=dummy_plan,
        intent=test_intent,
        steps_count=len(dummy_plan.steps),
        from_cache=False
    )
    time.sleep(0.2)
    
    if wm.get_current_task():
        print("SUCCESS: WorkingMemory tracking task")
    else:
        print("FAIL: WorkingMemory not tracking task")
        return

    print("\n--- PHASE 2: SIMULATE SUCCESSFUL COMPLETION ---")
    
    # Simulate step completions (optional but good for full test)
    for i, step in enumerate(dummy_plan.steps):
        emit(
            EventType.PLAN_STEP_COMPLETED,
            source="test",
            step_index=i,
            action=step.action,
            parameters=step.parameters,
            method_used="test_method",
            duration_ms=100.0,
            data={},
            verified=False,
            verify_confidence=None
        )
        time.sleep(0.1)

    # Now emit PLAN_COMPLETED
    # This triggers WorkingMemory._on_plan_completed which calls _persist_completed_task
    emit(
        EventType.PLAN_COMPLETED,
        source="test",
        plan=dummy_plan,
        intent=test_intent,
        execution_id="test_exec_123",
        duration_ms=500.0,
        step_results=[
            {
                "step_index": 0,
                "action": "launch_app",
                "parameters": {"app_name": "notepad"},
                "success": True,
                "method_used": "test_method",
                "duration_ms": 100.0
            },
            {
                "step_index": 1,
                "action": "wait",
                "parameters": {"seconds": 1.5},
                "success": True,
                "method_used": "test_method",
                "duration_ms": 100.0
            }
        ],
        context={}
    )
    
    # Wait for processing
    time.sleep(0.5)

    print("\n--- PHASE 3: VERIFY DATABASE ---")
    
    # Check what pattern was actually used
    # The pattern depends on _build_intent_pattern in planner
    expected_pattern = "open:notepad"
    # First, let's see what's in the database
    with store.transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT intent_pattern, use_count, success_count, failure_count, is_valid 
            FROM plan_cache 
            WHERE intent_pattern = ?
        """, (expected_pattern,))
        row = cursor.fetchone()
        
        if row:
            use_count = row[1]
            success_count = row[2]
            failure_count = row[3]
            is_valid = row[4]
            rate = success_count / use_count if use_count > 0 else 0
            print(f"DEBUG DATA:")
            print(f"  Uses: {use_count}")
            print(f"  Successes: {success_count}")
            print(f"  Failures: {failure_count}")
            print(f"  Is Valid: {is_valid}")
            print(f"  Calculated Rate: {rate:.2f} (Threshold is 0.7)")       
        else:
            print("WARNING: No plans in cache")
    
    # Try to get the cached plan
    cached = store.get_cached_plan(expected_pattern, min_success_rate=0.0, min_uses=28)
    
    if cached:
        print(f"SUCCESS: Plan found in cache!")
        print(f"   Pattern: {cached.get('intent_pattern')}")
        print(f"   Strategy: {cached.get('plan_strategy')}")
        print(f"   Use Count: {cached.get('use_count')}")
    else:
        print(f"FAIL: Plan NOT found for pattern '{expected_pattern}'")
        print("   Checking if pattern mismatch...")
        
        # Debug: Check what patterns exist
        with store.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT intent_pattern FROM plan_cache")
            patterns = [row[0] for row in cursor.fetchall()]
            if patterns:
                print(f"   Existing patterns: {patterns}")
            else:
                print("   No patterns in database at all")
        return

    print("\n--- PHASE 4: TEST PLANNER CACHE RECALL ---")
    print("Sending same intent to Planner...")
    print("Expected: Planner should return cached plan WITHOUT calling LLM")

    # Track what happens
    plan_events = []
    
    def on_plan_created(event):
        plan_events.append(event)
        from_cache = event.data.get("from_cache", False)
        if from_cache:
            print("SUCCESS: Planner used CACHE! (Fast Path)")
        else:
            print("INFO: Planner generated NEW plan (Slow Path)")

    def on_plan_failed(event):
        plan_events.append(event)
        print(f"FAIL: Plan creation failed: {event.data.get('reason')}")

    subscribe(EventType.PLAN_CREATED, on_plan_created)
    subscribe(EventType.PLAN_FAILED, on_plan_failed)

    # Fire the intent!
    start_time = time.time()
    emit(
        EventType.INTENT_RECOGNIZED,
        source="test",
        intent=test_intent
    )

    # Wait for processing
    time.sleep(2)
    elapsed = (time.time() - start_time) * 1000

    if plan_events:
        print(f"\n   Processing time: {elapsed:.0f}ms")
        if elapsed < 500:
            print("   FAST - likely cache hit")
        else:
            print("   SLOW - likely LLM call")
    else:
        print("FAIL: No PLAN_CREATED or PLAN_FAILED event received")

    print("\n--- PHASE 5: CLEANUP ---")
    emit(EventType.AGENT_STOPPED, source="test")
    time.sleep(0.2)
    print("Session ended")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    run_test()