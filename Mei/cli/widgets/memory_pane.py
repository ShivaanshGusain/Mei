"""
Memory pane — shows session stats and last episode info.
Updates on: MEMORY_SESSION_STARTED, MEMORY_SESSION_ENDED,
            MEMORY_STORED, MEMORY_PLAN_FOUND.
Called directly by MeiTUI.on_agent_event.
"""
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text
from textual.app import RenderResult
from textual.widget import Widget

from ...core.events import EventType
from ..event_bridge import AgentEvent


class MemoryPane(Widget):
    """Displays Kùzu memory session and episode stats."""

    DEFAULT_CSS = """
    MemoryPane {
        height: 100%;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session_id      = "none"
        self._last_stability  = "-"
        self._last_command    = "-"
        self._last_tier       = "-"

    def render(self) -> RenderResult:
        lines = Text()
        lines.append("Session:    ", style="bold")
        lines.append(f"{self._session_id[:28]}\n", style="white")
        lines.append("Last cmd:   ", style="bold")
        lines.append(f"{escape(self._last_command[:35])}\n", style="white")
        lines.append("Last tier:  ", style="bold")
        lines.append(f"{self._last_tier}\n", style="cyan")
        lines.append("Last stab:  ", style="bold")
        lines.append(f"{self._last_stability}\n", style="cyan")

        return Panel(lines, title="[bold]MEMORY[/bold]", border_style="blue")

    def on_agent_event(self, msg: AgentEvent) -> None:
        event = msg.agent_event
        et    = event.type
        data  = event.data

        if et == EventType.MEMORY_SESSION_STARTED:
            self._session_id = data.get("session_id", "?")
            self.refresh()

        elif et == EventType.MEMORY_SESSION_ENDED:
            self._session_id = "ended"
            self.refresh()

        elif et == EventType.MEMORY_PLAN_FOUND:
            self._last_tier    = str(data.get("tier", "?"))
            self._last_command = data.get("raw_command", self._last_command)
            stab = data.get("stability_score")
            if stab is not None:
                self._last_stability = f"{stab:.3f}"
            self.refresh()
