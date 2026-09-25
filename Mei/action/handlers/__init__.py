from .window import register_window_tools
from .app import register_app_tools
from .input import register_input_tools
from .web import register_web_tools
from .system import register_system_tools
from .utility import register_utility_tools


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
    
    try:
        register_web_tools(executor)
    except Exception as e:
        print(f"Failed to register web tools: {e}")
    
    try:
        register_system_tools(executor)
    except Exception as e:
        print(f"Failed to register system tools: {e}")

    try:
        register_utility_tools(executor)
    except Exception as e:
        print(f"Failed to register utility tools: {e}")
        
    print(f"Total tools registered: {len(executor.list_actions())}")

__all__ = ['register_all_tools']