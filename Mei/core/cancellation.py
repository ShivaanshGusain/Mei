"""
Global soft-cancellation token for the MicroPlanner execution loop.

Usage:
    from Mei.core.cancellation import get_cancellation_token
    token = get_cancellation_token()
    token.cancel()        # called from TUI Escape binding
    token.reset()         # called at start of each new command
    token.is_cancelled    # checked in MicroPlanner between steps
"""
import threading


class CancellationToken:
    """
    Thread-safe cancellation flag backed by threading.Event.
    threading.Event is exactly this primitive — no hand-rolled lock needed.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Signal cancellation. MicroPlanner checks this before each step."""
        self._event.set()

    def reset(self) -> None:
        """Clear the flag. Call when a new command is submitted."""
        self._event.clear()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


_global_token = CancellationToken()


def get_cancellation_token() -> CancellationToken:
    """Return the process-global cancellation token."""
    return _global_token
