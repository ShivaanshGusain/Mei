from .window import get_window_handlers, WINDOW_HANDLERS
from .app import get_app_handlers, APP_HANDLERS
from .input import get_input_handlers, INPUT_HANDLERS
from .navigation import get_navigation_handlers, NAVIGATION_HANDLERS
from .utility import get_util_handers, UTIL_HANDLERS

def get_all_handlers():
    """Get instances of all handlers."""
    handlers = []
    handlers.extend(get_window_handlers())
    handlers.extend(get_app_handlers())
    handlers.extend(get_input_handlers())
    handlers.extend(get_navigation_handlers())
    handlers.extend(get_utility_handlers())
    return handlers

__all__ = [
    'get_window_handlers', 'WINDOW_HANDLERS',
    'get_app_handlers', 'APP_HANDLERS',
    'get_input_handlers', 'INPUT_HANDLERS',
    'get_navigation_handlers', 'NAVIGATION_HANDLERS',
    'get_util_handlers', 'UTILITY_HANDLERS',
    'get_all_handlers',
]

