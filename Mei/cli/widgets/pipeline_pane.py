"""
Pipeline pane — shows current execution tier, confidence, stability, status.

Updates on:
  MEMORY_PLAN_FOUND, MEMORY_PLAN_NOT_FOUND, TRANSCRIBE_COMPLETED,
  PLAN_COMPLETED, PLAN_FAILED, AGENT_STARTED, AGENT_STOPPED.

Note on message routing:
  Textual messages bubble UP the DOM. AgentEvent is posted to the App,
  which dispatches to panes explicitly via on_agent_event in MeiTUI.
  The on_agent_event method here is called directly by the App, not
  through Textual's normal event dispatch.
"""
from rich.panel import Panel
from rich.text import Text
from textual.app import RenderResult
from textual.widget import Widget

from ...core.events import EventType
from ..event_bridge import AgentEvent


class PipelinePane(Widget):
    """Displays pipeline status, tier, confidence, and stability."""

    DEFAULT_CSS = """
    PipelinePane {
        height: 100%;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._status = "IDLE"
        self._command = ""
        self._tier = "-"
        self._confidence = "-"
        self._stability = "-"

    def render(self) -> RenderResult:
        status_color = {
            "IDLE":       "dim",
            "EXECUTING":  "green",
            "CANCELLING": "yellow",
            "FAILED":     "red",
            "CANCELLED":  "dim",
            "COMPLETED":  "green",
        }.get(self._status, "white")

        lines = Text()
        lines.append("Status:     ", style="bold")
        lines.append(f"● {self._status}\n", style=status_color)
        lines.append("Command:    ", style="bold")
        lines.append(f"{self._command[:40]}\n", style="white")
        lines.append("Tier:       ", style="bold")
        lines.append(f"{self._tier}\n", style="cyan")
        lines.append("Confidence: ", style="bold")
        lines.append(f"{self._confidence}\n", style="cyan")
        lines.append("Stability:  ", style="bold")
        lines.append(f"{self._stability}\n", style="cyan")

        return Panel(lines, title="[bold]PIPELINE[/bold]", border_style="blue")

    def on_agent_event(self, msg: AgentEvent) -> None:
        """Called directly by MeiTUI.on_agent_event — not Textual dispatch."""
        event = msg.agent_event
        et = event.type

        if et == EventType.TRANSCRIBE_COMPLETED:
            self._command = event.data.get("text", "")[:40]
            self._status = "EXECUTING"
            self.refresh()

        elif et == EventType.MEMORY_PLAN_FOUND:
            self._tier = str(event.data.get("tier", "?"))
            conf = event.data.get("confidence", 0.0)
            self._confidence = f"{conf:.4f}"
            stab = event.data.get("stability_score")
            if stab is not None:
                self._stability = f"{stab:.3f}"
            self.refresh()

        elif et == EventType.MEMORY_PLAN_NOT_FOUND:
            self._tier = "3 (decompose)"
            self._confidence = "-"
            self._stability = "-"
            self.refresh()

        elif et == EventType.PLAN_COMPLETED:
            self._status = "COMPLETED"
            self.refresh()

        elif et == EventType.PLAN_FAILED:
            reason = event.data.get("reason", "")
            self._status = "CANCELLED" if reason == "cancelled" else "FAILED"
            self.refresh()

        elif et in (EventType.AGENT_STARTED, EventType.AGENT_STOPPED):
            self._status = "IDLE"
            self.refresh()
