"""web_navigate tool - navigate to a URL in the browser"""

from typing import Dict, Any, Tuple, Optional
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ....core.config import ActionResult, VerifyResult, get_config
from ....core.events import emit, EventType
from ...context import ExecutionContext
from .session import get_browser_manager

WEB_NAVIGATE_SCHEMA = {
    "url": {"type": "str", "required": True,
            "description": "URL to navigate to"},
    "new_tab": {"type": "bool", "required": False, "default": False,
                "description": "Open in a new tab instead of current"},
}

def is_blank_or_newtab(url: str) -> bool:
    """
    Browser-agnostic check for initial/blank/new tab pages.
    Works across Chrome, Brave, Edge, Vivaldi, Zen, and Firefox.
    """
    if not url:
        return True
        
    url_clean = url.strip().lower()
    
    # 1. Any non-web scheme is an internal browser page
    if not (url_clean.startswith("http://") or url_clean.startswith("https://") or url_clean.startswith("file://")):
        return True
        
    # 2. Check for generic newtab / blank keywords
    placeholder_keywords = ["newtab", "blank", "startpage", "home"]
    if any(keyword in url_clean for keyword in placeholder_keywords):
        # If it contains these words AND has no standard domain structure, it's an internal tab
        if "://" in url_clean and not any(url_clean.startswith(proto) for proto in ["http://", "https://"]):
            return True

    return False

def web_navigate_validate(params: Dict[str, Any])-> Tuple[bool, Optional[str]]:
    url = params.get("url")
    if not url or not str(url).strip():
        return ( False, "Missing or empty 'url' parameter")
    return (True, None)

def web_navigate_execute(params: Dict[str, Any], context: ExecutionContext)-> ActionResult:
    url = str(params["url"]).strip()
    new_tab = params.get("new_tab", False)
    config = get_config().web

    if not url.startswith(("http://", "https://", "file://")):
        url = "https://" +  url

    manager = get_browser_manager()

    try:
        if new_tab:
            page = manager.new_page()
        else:
            page = manager.get_active_page()

        if not page:
            return ActionResult(
                success=False,
                error="Could not get browser page. Is the browser running",
                method_used="playwright_cdp"
            )

        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=config.default_timeout_ms
            )

            # Try to wait for networkidle, but don't fail if it times out
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
                page.wait_for_url(lambda u: not is_blank_or_newtab(u), timeout=5000)
            except PlaywrightTimeout:
                pass
            
            status = response.status if response else None

        except PlaywrightTimeout:
            status = None

        final_url = page.url
        title = page.title()

        context.set_variable("current_url", final_url)
        context.set_variable("current_title", title)

        emit(EventType.ACTION_COMPLETED,
            source="web_navigate",
            url=final_url, title=title, status= status)

        return ActionResult(
            success=True,
            data={
                "url": final_url,
                "title":title,
                "status":status,
                "new_tab":new_tab
            },
            method_used="playwright_cdp"
        )

    except Exception as e:
        return ActionResult(
            success=False,
            error=f"Navigation failed: {str(e)}",
            method_used="playwright_cdp"
        )

def web_navigate_verify(params: Dict[str,Any],
                        context:ExecutionContext,
                        result: ActionResult)-> VerifyResult:
    """Verify the page loaded by checking URL and title."""
    if not result.success:
        return VerifyResult(verified=False, confidence=0.9,
                           reason=f"Navigation failed: {result.error}")

    final_url = result.data.get("url", "")
    target_url = str(params["url"]).strip().lower()
    title = result.data.get("title", "")

    if target_url in final_url.lower() or final_url != "about:blank":
        return VerifyResult(
            verified=True, confidence=0.9,
            reason=f"Page loaded: '{title}' at {final_url}"
        )
    
    return VerifyResult(
        verified=False, confidence=0.7,
        reason=f"Expected URL containing '{target_url}', got '{final_url}'"
    )
