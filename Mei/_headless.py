"""
Headless agent runner — fallback when the TUI is unavailable or broken.

Run with:  py app.py --headless

Use this when:
  - The Textual TUI itself has a bug you need to debug
  - You want plain terminal output without the alternate screen
  - Running in a minimal environment without a proper terminal
"""
import os
import threading
import time

from .core.config import init_config
from .core.events import EventType, emit
from .core.pipeline import start_pipeline, stop_pipeline, process_text
from .action.executor import get_executor
from .memory.working import get_working_memory


def run_headless() -> None:
    from .core.run_logger import install_run_logging
    install_run_logging()

    print("Starting Mei (headless mode)...")

    init_config()
    working_memory = get_working_memory()
    executor = get_executor()
    print(f"Executor ready: {len(executor.list_actions())} tools registered")

    emit(EventType.AGENT_STARTED, source="headless")
    start_pipeline()

    def _text_input_thread() -> None:
        time.sleep(1)
        print("\n--- Headless mode (type commands, 'quit' to exit) ---")
        while True:
            try:
                cmd = input().strip()
                if cmd.lower() in ("quit", "exit", "q"):
                    print("Shutting down...")
                    os._exit(0)
                if cmd:
                    process_text(cmd)
            except EOFError:
                print("EOF received. Shutting down...")
                os._exit(0)
            except Exception:
                break

    input_thread = threading.Thread(target=_text_input_thread, daemon=True)
    input_thread.start()

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass

    emit(EventType.AGENT_STOPPED, source="headless")
    stop_pipeline()
    print("Mei stopped.")
