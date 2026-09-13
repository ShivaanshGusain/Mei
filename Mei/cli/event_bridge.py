"""
TUI Event Bridge — connects the agent's EventBus to the Textual app.

Uses post_message() (thread-safe Textual API) to push agent events
to the TUI without polling or queues. Zero latency, no timer needed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from textual.message import Message

from ..core.events import get_event_bus, Event

if TYPE_CHECKING:
    from textual.app import App


class AgentEvent(Message):
    """Wraps an agent Event for delivery to Textual widgets via the DOM."""

    def __init__(self, event: Event) -> None:
        super().__init__()
        self.agent_event = event


class TUIEventBridge:
    """
    Subscribes to the global EventBus (subscribe_all) and posts each
    incoming event to the Textual app via post_message() — which is
    thread-safe and works correctly from agent worker threads.

    Usage:
        bridge = get_event_bridge()
        bridge.attach(self)   # call from MeiTUI.on_mount
    """

    def __init__(self) -> None:
        self._app: App | None = None

    def attach(self, app: "App") -> None:
        """Call once from MeiTUI.on_mount after the app is running."""
        self._app = app
        get_event_bus().subscribe_all(self._on_event)

    def _on_event(self, event: Event) -> None:
        """Called from agent worker thread — posts to app's message queue."""
        if self._app is not None:
            try:
                self._app.post_message(AgentEvent(event))
            except Exception:
                pass  # app may be shutting down; ignore silently


_bridge = TUIEventBridge()


def get_event_bridge() -> TUIEventBridge:
    """Return the process-global event bridge."""
    return _bridge
