from typing import Optional, Dict, Any, List
from datetime import datetime

from ...core.task import IntentSequence, StepExecutionStatus
from ...core.events import emit, EventType
from ...core.cancellation import get_cancellation_token
from ..llm.engine import get_llm_engine
from .prompt_builder import build_step_prompt
from .evaluator import verify_step
from ...action.executor import get_executor
from ...action.context import ExecutionContext

class MicroPlanner:
    def __init__(self):
        self._llm = get_llm_engine("planner")
        self._executor = get_executor()
    def _sanitize_data(self, data: Any) -> Any:
        """Recursively convert non-serializable types to strings."""
        if isinstance(data, dict):
            return {k: self._sanitize_data(v) for k, v in data.items()}
        elif isinstance(data, (list, tuple)):
            return [self._sanitize_data(v) for v in data]
        elif isinstance(data, set):
            return list(data)
        elif isinstance(data, (str, int, float, bool)) or data is None:
            return data
        else:
            return str(data)

    def execute_sequence(self, sequence: IntentSequence, context: ExecutionContext) -> bool:
        step_results = []
        
        while True:
            # ── Cancellation check — before each step ────────────────────────
            if get_cancellation_token().is_cancelled:
                emit(EventType.PLAN_FAILED, source="MicroPlanner", reason="cancelled")
                return False

            current_step = sequence.get_next_step()
            if not current_step:
                break

            current_step.status = StepExecutionStatus.RUNNING
            success = False

            while current_step.retry_count <= current_step.max_retries:
                prompt, tool_names = build_step_prompt(current_step, context)
                tool_call = self._llm.chat_tool_call(
                    messages=[{"role": "user", "content": prompt}],
                    tool_names=tool_names
                )
                print(f"\n[MicroPlanner X-RAY] LLM Tool Call: {tool_call}")
                if isinstance(tool_call, list) and len(tool_call) > 0:
                    tool_call = tool_call[0]

                if not tool_call or not isinstance(tool_call, dict):
                    current_step.retry_count += 1
                    continue

                result = self._executor.execute_single_action(
                    tool_call.get("action", ""), tool_call.get("parameters", {}), context
                )
                is_ok, reason = verify_step(current_step, result, context)

                print(f"[MicroPlanner X-RAY] Result: success={result.success}, error={result.error}, method={result.method_used}")
                print(f"[MicroPlanner X-RAY] Verify: ok={is_ok}, reason={reason}")

                if result.success and is_ok:
                    current_step.status = StepExecutionStatus.COMPLETED
                    success = True

                    # Track completed steps for planner context
                    completed = context.get_variable("completed_steps", [])
                    completed.append(f"{tool_call.get('action')}({tool_call.get('parameters', {})})")
                    context.set_variable("completed_steps", completed)

                    # Update window title for prompt
                    if context.current_window:
                        context.set_variable("current_window_title", context.current_window.title)

                    step_results.append({
                        "action": tool_call.get("action", ""),
                        "parameters": tool_call.get("parameters", {}),
                        "success": True,
                        "duration_ms": result.data.get("duration_ms", 0) if isinstance(result.data, dict) else 0,
                        "data": self._sanitize_data(result.data),
                        "method_used": getattr(result, "method_used", "unknown"),
                        "step_description": current_step.description,        # 
                        "step_domain": current_step.domain,                  # 
                        "step_expected_output": current_step.expected_output, # 
                    })
                    try:
                        from ...cognition.observation import get_observation_builder
                        obs = get_observation_builder().build(
                            action=tool_call.get("action", ""),
                            parameters=tool_call.get("parameters", {}),
                            result=result,
                            target_app=current_step.target
                        )
                        context.set_variable("last_observation", obs)
                    except Exception as e:
                        print(f"[MicroPlanner] observation build failed: {e}")
                    break
                
                else:
                    current_step.retry_count += 1
                    context.set_variable("last_step_error", result.error or reason)
                    print(f"[MicroPlanner X-RAY] Retry {current_step.retry_count}/{current_step.max_retries}")

            if not success:
                current_step.status = StepExecutionStatus.FAILED
                emit(EventType.PLAN_FAILED, source="MicroPlanner")
                return False

        self._commit_to_graph(sequence, step_results, context.elapsed_time_ms() if hasattr(context, "elapsed_time_ms") else 0, context)
        return True
        
    def heal_from_failure(
        self,
        succeeded_steps: list,
        failed_step_index: int,
        failed_tool: str,
        failed_params: dict,
        failure_reason: str,
        remaining_intent_steps: list,
        original_command: str,
        context: ExecutionContext,
    ) -> bool:
        """
        Called when direct execution (Tier 1) or planner-assisted execution (Tier 2)
        hits a step failure mid-sequence.

        Builds rich context about what succeeded and what failed, then hands
        the remaining unexecuted steps to execute_sequence for LLM-assisted recovery.

        SLMs need explicit state — they cannot infer what happened before.
        """
        from ...core.task import IntentSequence

        print(f"[MicroPlanner] Healing from step {failed_step_index + 1} failure: {failure_reason}")
        print(f"[MicroPlanner] {len(succeeded_steps)} step(s) succeeded, "
              f"{len(remaining_intent_steps)} step(s) remaining.")

        # Build succeeded summary for prompt context
        succeeded_summary = "\n".join(
            f"  * Step {i + 1}: {tool}({params}) -> success"
            for i, (tool, params, _) in enumerate(succeeded_steps)
        )

        # Inject heal context — build_step_prompt picks this up
        context.set_variable("heal_context", {
            "succeeded": succeeded_summary,
            "failed_tool": failed_tool,
            "failed_params": str(failed_params),
            "failure_reason": failure_reason,
            "original_command": original_command,
        })
        context.set_variable("last_step_error", failure_reason)

        # Populate completed_steps so COMPLETED STEPS SO FAR shows correctly
        completed = [
            f"{tool}({params})" for tool, params, _ in succeeded_steps
        ]
        context.set_variable("completed_steps", completed)

        if not remaining_intent_steps:
            print("[MicroPlanner] No remaining steps — healing complete.")
            return True

        heal_sequence = IntentSequence(
            raw_command=original_command,
            steps=remaining_intent_steps,
            is_verified_macro=False,
            confidence=0.0,
        )

        return self.execute_sequence(heal_sequence, context)

    def _commit_to_graph(self, sequence, step_results, duration_ms, context):
        try:
            matched_goal_id = context.get_variable("matched_goal_id")
            if matched_goal_id:
                try:
                    from ...memory.graph.procedural import update_goal_stats
                    update_goal_stats(matched_goal_id, success=True, duration_ms=duration_ms)
                    print(f"[Memory] Updated existing goal {matched_goal_id}")
                    return
                except Exception as e:
                    print(f"[Memory] Failed to update goal stats: {e}")

            from ...memory.graph.episodic import write_episode
            from ...memory.graph.stability import score_episode
            session_id = context.get_variable("session_id", "unknown")

            stability = score_episode(step_results)
            print(f"[Memory] Episode stability: {stability:.3f}")

            write_episode(
                execution_id=f"exec_{int(datetime.now().timestamp()*1000)}",
                session_id=session_id,
                intent={
                    "action": sequence.steps[0].domain if sequence.steps else "general",
                    "target": sequence.steps[0].target if sequence.steps else None,
                    "raw_command": sequence.raw_command,
                    "confidence": sequence.confidence,
                },
                step_results=step_results,
                success=True,
                duration_ms=duration_ms,
                stability_score=stability,
            )
        except ImportError:
            print("[Memory] episodic memory write_episode not found, skipping commit.")
        except Exception as e:
            print(f"[Memory] Failed to write graph episode: {e}")


_planner_instance: Optional[MicroPlanner] = None

def get_microplanner() -> MicroPlanner:
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = MicroPlanner()
    return _planner_instance
