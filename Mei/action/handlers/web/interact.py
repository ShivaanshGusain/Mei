"""web_click and web_type tools - interact with web page elements."""

from typing import Dict, Any, Tuple, Optional
from playwright.sync_api import TimeoutError as PlaywrightTimeout, Page, Locator

from ....core.config import ActionResult, VerifyResult,get_config
from ....core.events import emit, EventType
from ...context import ExecutionContext
from .session import get_browser_manager

def _resolve_locator(page: Page, selector: str, selector_type: str = "text")-> Locator:
    """
    Map selector_type to the correct Playwright locator.
    
    Supported types:
        text        → page.get_by_text(selector)
        role        → page.get_by_role(selector)
        placeholder → page.get_by_placeholder(selector)
        label       → page.get_by_label(selector)
        css         → page.locator(selector)     # raw CSS
        xpath       → page.locator(selector)     # raw XPath
        testid      → page.get_by_test_id(selector)
    """

    t = selector_type.lower().strip()

    if t == "text":
        return page.get_by_text(selector, exact=False)
    elif t == "role":
        return page.get_by_role(selector)
    elif t == "placeholder":
        return page.get_by_placeholder(selector)
    elif t == "label":
        return page.get_by_label(selector)
    elif t == "testid":
        return page.get_by_test_id(selector)
    elif t in ("css", "xpath"):
        return page.locator(selector)
    else:
        # Default: try text first
        return page.get_by_text(selector, exact=False)

"""——————————WEB CLICK——————————"""
WEB_CLICK_SCHEMA = {
    "selector": {"type": "str", "required": True,
                 "description": "Element to click (text, CSS, etc.)"},
    "selector_type": {"type": "str", "required": False,
                      "default": "text",
                      "description": "text|role|placeholder|label|css|xpath|testid"},
}

def web_click_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    if not params.get("selector"):
        return (False, "Missing 'selector' parameter")
    return (True, None)

def web_click_execute(params:Dict[str,Any], context: ExecutionContext)->ActionResult:
    selector = str(params["selector"])
    selector_type = params.get("selector_type", "text")
    config = get_config().web
    
    manager = get_browser_manager()
    page = manager.get_active_page()

    if not page:
        return ActionResult(
            success=False,
            error="No active browser page",
            method_used="playwright_cdp"
        )
    
    try:
        locator = _resolve_locator(page, selector, selector_type)
        locator.click(timeout=config.action_timeout_ms)
        page.wait_for_timeout(300)
        emit(EventType.ACTION_COMPLETED,
             source="web_click",
             selector=selector, selector_type=selector_type)

        return ActionResult(
            success=True,
            data={
                "selector": selector,
                "selector_type": selector_type,
                "page_url": page.url,
                "page_title": page.title(),
            },
            method_used="playwright_cdp"
        )

    except PlaywrightTimeout:
        return ActionResult(
            success=False,
            error=f"Element not found or not clickable within "
                  f"{config.action_timeout_ms}ms: "
                  f"{selector_type}='{selector}'",
            method_used="playwright_cdp"
        )
    except Exception as e:
        return ActionResult(
            success=False,
            error=f"web_click failed: {str(e)}",
            method_used="playwright_cdp"
        )


"""——————————WEB TYPE——————————"""

WEB_TYPE_SCHEMA = {
    "selector": {"type": "str", "required": True,
                 "description": "Input element to type into"},
    "selector_type": {"type": "str", "required": False,
                      "default": "text",
                      "description": "text|role|placeholder|label|css|xpath|testid"},
    "text": {"type": "str", "required": True,
             "description": "Text to type"},
    "clear_first": {"type": "bool", "required": False, "default": True,
                    "description": "Clear existing text before typing"},
    "submit": {"type": "bool", "required": False, "default": False,
               "description": "Press Enter after typing"},
}



def web_type_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    if not params.get("selector"):
        return (False, "Missing 'selector' parameter")
    if "text" not in params:
        return (False, "Missing 'text' parameter")
    return (True, None)


def web_type_execute(params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
    selector = str(params["selector"])
    selector_type = params.get("selector_type", "text")
    text = str(params["text"])
    clear_first = params.get("clear_first", True)
    submit = params.get("submit", False)
    config = get_config().web
    
    manager = get_browser_manager()
    page = manager.get_active_page()

    if not page:
        return ActionResult(
            success=False,
            error="No active browser page",
            method_used="playwright_cdp"
        )
    
    try:
        locator = _resolve_locator(page, selector, selector_type)
        if clear_first:
            locator.fill(text, timeout=config.action_timeout_ms)

        else:
            locator.click(timeout=config.action_timeout_ms)
            locator.type(text)

        if submit:
            locator.press("Enter")
            # Wait briefly for form submission
            page.wait_for_timeout(500)
        
        emit(EventType.ACTION_COMPLETED,
             source="web_type",
             selector=selector, text_length=len(text), submit=submit)


        return ActionResult(
            success=True,
            data={
                "selector": selector,
                "text_typed": text,
                "clear_first": clear_first,
                "submitted": submit,
                "page_url": page.url,
            },
            method_used="playwright_cdp"
        )
    
    except PlaywrightTimeout:
        return ActionResult(
            success=False,
            error=f"Input element not found within "
                  f"{config.action_timeout_ms}ms: "
                  f"{selector_type}='{selector}'",
            method_used="playwright_cdp"
        )
    except Exception as e:
        return ActionResult(
            success=False,
            error=f"web_type failed: {str(e)}",
            method_used="playwright_cdp"
        )
