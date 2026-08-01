"""Web domain tools — Playwright-based browser automation via CDP."""

from .navigate import (
    web_navigate_validate, web_navigate_execute, web_navigate_verify,
    WEB_NAVIGATE_SCHEMA,
)
from .interact import (
    web_click_validate, web_click_execute, WEB_CLICK_SCHEMA,
    web_type_validate, web_type_execute, WEB_TYPE_SCHEMA,
)
from .state import (
    web_get_state_validate, web_get_state_execute, WEB_GET_STATE_SCHEMA,
    web_wait_for_validate, web_wait_for_execute, WEB_WAIT_FOR_SCHEMA,
)
from .scroll import (
    web_scroll_validate, web_scroll_execute, WEB_SCROLL_SCHEMA,
)


def register_web_tools(executor) -> None:
    """Register all web-domain tools with the executor."""
    
    executor.register(
        name="web_navigate",
        impl=web_navigate_execute,
        domain="web",
        schema=WEB_NAVIGATE_SCHEMA,
        validate_fn=web_navigate_validate,
        verify_fn=web_navigate_verify,
        requires_browser=True,
        cost=3,
        description="Navigate to a URL in the browser",
    )
    
    executor.register(
        name="web_click",
        impl=web_click_execute,
        domain="web",
        schema=WEB_CLICK_SCHEMA,
        validate_fn=web_click_validate,
        requires_browser=True,
        cost=2,
        description="Click on a web page element by text, role, CSS, etc.",
    )
    
    executor.register(
        name="web_type",
        impl=web_type_execute,
        domain="web",
        schema=WEB_TYPE_SCHEMA,
        validate_fn=web_type_validate,
        requires_browser=True,
        cost=2,
        description="Type text into a web page input field",
    )
    
    executor.register(
        name="web_get_state",
        impl=web_get_state_execute,
        domain="web",
        schema=WEB_GET_STATE_SCHEMA,
        validate_fn=web_get_state_validate,
        requires_browser=True,
        cost=1,
        description="Get current page state: text content, links, or inputs",
    )
    
    executor.register(
        name="web_wait_for",
        impl=web_wait_for_execute,
        domain="web",
        schema=WEB_WAIT_FOR_SCHEMA,
        validate_fn=web_wait_for_validate,
        requires_browser=True,
        cost=1,
        description="Wait for a web element to become visible/hidden",
    )
    
    executor.register(
        name="web_scroll",
        impl=web_scroll_execute,
        domain="web",
        schema=WEB_SCROLL_SCHEMA,
        validate_fn=web_scroll_validate,
        requires_browser=True,
        cost=1,
        description="Scroll the web page up or down",
    )
    
    print("[WebTools] 6 web tools registered")