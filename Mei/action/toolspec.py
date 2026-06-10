from dataclasses import dataclass, field
from typing import Literal, Callable, Dict, Any,Type, Optional
from .context import ExecutionContext


@dataclass
class ToolSpec:
    """Metadata + implementation for a single tool/action"""

    #──Required─────────────────────────────────────────────────────────────────
    name:str            #Ex: "launch_app"

    domain : Literal["web","gui","system","app","workspace"] 
    #[TODO] Requires changes and additions later on

    impl: Callable      #(params, context)-> ActionResult

    #──Schema ( Parameter definition ) ─────────────────────────────────────────
    # A plan dictionary describing expected params. 
    # Keys = parameter names, values = {"type": ..., "required": bool}
    schema : Dict[str,Any] = field(default_factory=dict)

    #──Optional Callable────────────────────────────────────────────────────────
    validate_fn: Optional[Callable] = None          # (params) -> (bool, Optional[str])
    verify_fn  : Optional[Callable] = None          # (params,context,result) -> VerifyResult
    
    requires_screen : bool = False                   # Needs a screenshot before
    requires_browser: bool = False                   # Needs an active browser
    requires_window : bool = False                   # Needs any active window
    requires_ui_tree: bool = False                   # Needs accessibility tree
    cost : int = 1                                   # 1 -> cheap, 5 -> costly

    supports_verification : bool = False
    description : str = ""

    def __post_init__(self):
        # Auto-set supports_verification from verify_fn presence
        if self.verify_fn is not None and not self.supports_verification:
            self.supports_verification = True


"""
Note to self ->
pydantic.Field wont work unless ToolSpec is not the child of pydantic.BaseModel

Also creates an issue of import coupling and is a heavyweight class, will slowdown the process during the runtime.
"""
