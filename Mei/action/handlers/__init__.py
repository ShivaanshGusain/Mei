from .window import register_window_tools
from .app import register_app_tools
from .input import register_input_tools
from .navigation import get_navigation_handlers, NAVIGATION_HANDLERS
from .utility import get_util_handers, UTIL_HANDLERS
"""
def get_all_handlers():
    #Get instances of all handlers.
    handlers = []
    handlers.extend(get_window_handlers())
    handlers.extend(get_app_handlers())
    handlers.extend(get_input_handlers())
    handlers.extend(get_navigation_handlers())
    handlers.extend(get_util_handers())
    return handlers
"""

def register_all_tools(executor) -> None:
    """Register every tool with the executor. Called once at init."""
    try:
        register_app_tools(executor)
    except Exception as e:
        print(f"Failed to register app tools: {e}")

    try:
        register_window_tools(executor)
    except Exception as e:
        print(f"Failed to register gui tools: {e}")
    
    try:
        register_input_tools(executor)
    except Exception as e:
        print(f"Failed to register input tools: {e}")
    e
    try:
        register_web_tools(executor)
    except Exception as e:
        print(f"Failed to register web tools: {e}")
    
    try:
        register_system_tools(executor)
    except Exception as e:
        print(f"Failed to register system tools: {e}")
    
    print(f"Total tools registered: {len(executor.list_actions())}")

__all__ = [
    'get_window_handlers', 'WINDOW_HANDLERS',
    'get_app_handlers', 'APP_HANDLERS',
    'get_input_handlers', 'INPUT_HANDLERS',
    'get_navigation_handlers', 'NAVIGATION_HANDLERS',
    'get_util_handers', 'UTIL_HANDLERS',
    'get_all_handlers',
]