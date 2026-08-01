"""web_scroll tool scroll within the browser page."""
from typing import Dict, Any, Tuple, Optional

from ....core.config import ActionResult, get_config
from ....core.events import emit, EventType
from ...context import ExecutionContext
from .session import get_browser_manager


WEB_SCROLL_SCHEMA = {
    "direction": {"type": "str", "required": True,
                  "description": "up|down"},
    "amount": {"type": "int", "required": False, "default": 800,
               "description": "Pixels to scroll"},
}


def web_scroll_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    direction = params.get("direction", "").lower()
    if direction not in ("up", "down"):
        return (False, f"direction must be 'up' or 'down', got '{direction}'")
    return (True, None)


def web_scroll_execute(params: Dict[str, Any],
                       context: ExecutionContext) -> ActionResult:
    direction = params["direction"].lower()
    amount = params.get("amount", 800)
    
    manager = get_browser_manager()
    page = manager.get_active_page()
    
    if not page:
        return ActionResult(
            success=False,
            error="No active browser page",
            method_used="playwright_cdp"
        )
    
    try:
        delta_y = amount if direction == "down" else -amount
        
        page.mouse.wheel(0, delta_y)
        
        page.wait_for_timeout(300)
        
        scroll_pos = page.evaluate(
            "() => ({ x: window.scrollX, y: window.scrollY, "
            "height: document.body.scrollHeight })"
        )
        
        return ActionResult(
            success=True,
            data={
                "direction": direction,
                "amount": amount,
                "scroll_y": scroll_pos.get("y", 0),
                "page_height": scroll_pos.get("height", 0),
            },
            method_used="playwright_cdp"
        )
    
    except Exception as e:
        return ActionResult(
            success=False,
            error=f"web_scroll failed: {str(e)}",
            method_used="playwright_cdp"
        )