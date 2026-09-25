from typing import List, Dict, Any

from ...core.task import IntentStep
from ...core.config import ActionResult
from ...action.context import ExecutionContext

# Domains verify_step() actually has a real, domain-specific check for.
# "utility"/"input"/"unknown" steps (e.g. wait, hotkey) fall through to the
# trivial "nothing to check, assume ok" case below and are not, by themselves,
# evidence that the user's goal was achieved.
_VERIFIABLE_DOMAINS = {"app", "window", "web", "file"}


def sequence_has_verified_evidence(step_results: List[Dict[str, Any]]) -> bool:
    """
    Goal-level signal: True only if at least one step in the sequence went
    through a real domain-specific check, not just "no error occurred".
    A sequence made entirely of trivial steps (e.g. just `wait`) succeeding
    is not, on its own, proof the requested outcome actually happened.
    """
    return any(sr.get("step_domain") in _VERIFIABLE_DOMAINS for sr in step_results)


def is_verifiable_domain(domain: str) -> bool:
    """Whether verify_step() has a real, domain-specific check for `domain`."""
    return domain in _VERIFIABLE_DOMAINS

def verify_step(step: IntentStep, result: ActionResult, context: ExecutionContext) -> tuple[bool, str]:
    """
    Step 1: If result.success is False, return (False, result.error).
    Step 2: Check domain-specific verification signals.
    Step 3: If no domain-specific check applies, return (True, "Success")
    """
    if not result.success:
        return (False, result.error or "Unknown error")
        
    domain = step.domain
    
    if domain == "app":
        # check if current_window is not None
        if not context.current_window:
            return (False, "No active window found after app operation")
            
    elif domain == "window":
        if step.target:
            fg = context.get_variable('current_window_title', '')
            if step.target.lower() not in fg.lower():
                return (False, f"Foreground window '{fg}' does not match target '{step.target}'")
                
    elif domain == "web":
      url = context.get_variable("current_url", "")
      if step.target and url:
          # Normalize both: strip protocol, www., trailing slash
          def _norm(u):
              u = u.lower().split("?")[0].split("#")[0]
              for prefix in ("https://www.", "http://www.", "https://", "http://"):
                  if u.startswith(prefix):
                      u = u[len(prefix):]
              return u.rstrip("/")

          if _norm(step.target) not in _norm(url) and _norm(url) not in _norm(step.target):
              return (False, f"Target '{step.target}' not found in current URL '{url}'")
        
    elif domain == "file":
      import os
      # Use the actual path from the tool result, not the step parameters
      path = (result.data.get("path") if isinstance(result.data, dict) else None) \
             or step.parameters.get("path") \
             or step.target
      if path:
          resolved = os.path.abspath(path)
          if not os.path.exists(resolved):
              return (False, f"Expected path '{resolved}' does not exist")
        
    return (True, "Success")
