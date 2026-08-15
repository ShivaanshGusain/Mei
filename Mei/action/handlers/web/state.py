"""web_get_state and web_wait_for tools — observe the browser."""

from typing import Dict, Any, Tuple, Optional
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from ....core.config import ActionResult, VerifyResult, get_config
from ....core.events import emit, EventType
from ...context import ExecutionContext
from .session import get_browser_manager
from .interact import _resolve_locator


# web_get_state

WEB_GET_STATE_SCHEMA = {
    "extract_type": {"type": "str", "required": False, "default": "text",
                     "description": "text|html|links|inputs|structured"},
}

def web_get_state_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    valid_types = {"text", "html", "links", "inputs", "structured"}
    extract_type = params.get("extract_type", "text")
    if extract_type not in valid_types:
        return (False, f"extract_type must be one of: {valid_types}")
    return (True, None)


def web_get_state_execute(params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
    extract_type = params.get("extract_type", "text")
    config = get_config().web
    max_len = config.max_page_text_length
    
    manager = get_browser_manager()
    page = manager.get_active_page()

    if not page:
        return ActionResult(
            success=False,
            error="No active browser page",
            method_used="playwright_cdp"
        )

    try:
        url = page.url
        title = page.title()
        
        data = {
            "url": url,
            "title": title,
            "extract_type": extract_type,
        }

        if extract_type == "text":
            text = page.inner_text("body", timeout=3000)
            data["content"] = text[:max_len]
            data["truncated"] = len(text) > max_len

        elif extract_type == "html":
            html = page.content()
            clean_text = _html_to_text(html)
            data["content"] = clean_text[:max_len]
            data["truncated"] = len(clean_text) > max_len

        elif extract_type == "links":
            links = page.eval_on_selector_all(
                "a[href]",
            """elements => elements
                .filter(el => el.offsetParent !== null)
                .slice(0, 50)
                .map(el => ({
                    text: el.innerText.trim().substring(0, 80),
                    href: el.href
                }))
            """)
            data["links"] = links
            data["link_count"] = len(links)
            
        elif extract_type == "inputs":
            inputs = page.eval_on_selector_all(
                "input, button, textarea, select, [role='button'], "
                "[role='textbox'], [role='link'], [contenteditable='true']",
                """elements => elements
                    .filter(el => el.offsetParent !== null)
                    .slice(0, 50)
                    .map(el => ({
                        tag: el.tagName.toLowerCase(),
                        type: el.type || el.getAttribute('role') || '',
                        name: el.name || '',
                        placeholder: el.placeholder || '',
                        value: el.value ? el.value.substring(0, 50) : '',
                        text: el.innerText ? el.innerText.trim().substring(0, 50) : '',
                        aria_label: el.getAttribute('aria-label') || '',
                        id: el.id || '',
                        visible: true
                    }))
                """
            )
            data["inputs"] = inputs
            data["input_count"] = len(inputs)
            
        elif extract_type == "structured":
            # Combined: text + links + inputs (for full page understanding)
            text = page.inner_text("body", timeout=3000)
            data["content"] = text[:max_len // 2]
            
            links = page.eval_on_selector_all(
                "a[href]",
                """elements => elements
                    .filter(el => el.offsetParent !== null)
                    .slice(0, 20)
                    .map(el => ({
                        text: el.innerText.trim().substring(0, 60),
                        href: el.href
                    }))
                """
            )
            data["links"] = links
            
            inputs = page.eval_on_selector_all(
                "input, button, textarea, select",
                """elements => elements
                    .filter(el => el.offsetParent !== null)
                    .slice(0, 20)
                    .map(el => ({
                        tag: el.tagName.toLowerCase(),
                        type: el.type || '',
                        placeholder: el.placeholder || '',
                        text: el.innerText ? el.innerText.trim().substring(0, 40) : '',
                        aria_label: el.getAttribute('aria-label') || ''
                    }))
                """
            )
            data["inputs"] = inputs
        
        context.set_variable("current_url", url)
        context.set_variable("current_title", title)
        
        return ActionResult(
            success=True,
            data=data,
            method_used="playwright_cdp"
        )
    
    except Exception as e:
        return ActionResult(
            success=False,
            error=f"web_get_state failed: {str(e)}",
            method_used="playwright_cdp"
        )

def _html_to_text(html: str) -> str:
    """Convert HTML to readable plain text."""
    try:
        # Try html2text if available
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0  # Don't wrap
        return h.handle(html)
    except ImportError:
        pass
    
    try:
        # Fallback: BeautifulSoup
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # Remove script and style elements
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except ImportError:
        pass
    
    # Last resort: basic regex stripping
    import re
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

WEB_WAIT_FOR_SCHEMA = {
    "selector": {"type": "str", "required": True,
                 "description": "Element to wait for"},
    "selector_type": {"type": "str", "required": False, "default": "text",
                      "description": "text|role|placeholder|label|css|xpath|testid"},
    "state": {"type": "str", "required": False, "default": "visible",
              "description": "visible|hidden|attached|detached"},
    "timeout_ms": {"type": "int", "required": False, "default": 5000,
                   "description": "Max wait time in milliseconds"},
}

def web_wait_for_validate(params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    if not params.get("selector"):
        return (False, "Missing 'selector' parameter")
    state = params.get("state", "visible")
    if state not in ("visible", "hidden", "attached", "detached"):
        return (False, f"Invalid state: '{state}'. "
                       f"Must be visible|hidden|attached|detached")
    return (True, None)


def web_wait_for_execute(params: Dict[str, Any],
                         context: ExecutionContext) -> ActionResult:
    selector = str(params["selector"])
    selector_type = params.get("selector_type", "text")
    state = params.get("state", "visible")
    timeout_ms = params.get("timeout_ms", 5000)
    
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
        locator.wait_for(state=state, timeout=timeout_ms)
        
        return ActionResult(
            success=True,
            data={
                "selector": selector,
                "selector_type": selector_type,
                "state": state,
                "found": True,
            },
            method_used="playwright_cdp"
        )
    
    except PlaywrightTimeout:
        return ActionResult(
            success=False,
            error=f"Timed out waiting for element '{selector}' "
                  f"to become {state} ({timeout_ms}ms)",
            data={"selector": selector, "state": state, "found": False},
            method_used="playwright_cdp"
        )
    except Exception as e:
        return ActionResult(
            success=False,
            error=f"web_wait_for failed: {str(e)}",
            method_used="playwright_cdp"
        )
