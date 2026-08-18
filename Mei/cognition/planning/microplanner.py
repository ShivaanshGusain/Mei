from typing import Optional, Dict, Any, List
from datetime import datetime

from ...core.task import IntentSequence, StepExecutionStatus
from ...core.events import emit, EventType
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
        
    def _commit_to_graph(self, sequence, step_results, duration_ms, context):
        try:
            from ...memory.graph.episodic import write_episode
            session_id = context.get_variable("session_id", "unknown")
            
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
