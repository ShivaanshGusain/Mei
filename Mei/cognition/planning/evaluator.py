from ...core.task import IntentStep
from ...core.config import ActionResult
from ...action.context import ExecutionContext

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
