"""
Model pane — shows intent/planner/embedder load states.
Updates on: LLM_LOADING, LLM_LOADED, LLM_UNLOADED.
Called directly by MeiTUI.on_agent_event.
"""
from rich.panel import Panel
from rich.text import Text
from textual.app import RenderResult
from textual.widget import Widget

from ...core.events import EventType
from ..event_bridge import AgentEvent


class ModelPane(Widget):
    """Displays LLM and embedder load status."""

    DEFAULT_CSS = """
    ModelPane {
        height: 100%;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._intent_state  = "unloaded"
        self._planner_state = "unloaded"
        self._embed_state   = "unloaded"

    @staticmethod
    def _icon(state: str) -> tuple[str, str]:
        """Return (icon, color) for a model state."""
        return {
            "unloaded": ("○", "dim"),
            "loading":  ("⟳", "yellow"),
            "loaded":   ("●", "green"),
        }.get(state, ("?", "white"))

    def render(self) -> RenderResult:
        lines = Text()
        for label, state in [
            ("Intent  ", self._intent_state),
            ("Planner ", self._planner_state),
            ("Embed   ", self._embed_state),
        ]:
            icon, color = self._icon(state)
            lines.append(f"{label}  ", style="bold")
            lines.append(f"{icon} {state}\n", style=color)

        return Panel(lines, title="[bold]MODELS[/bold]", border_style="blue")

    def on_agent_event(self, msg: AgentEvent) -> None:
        event = msg.agent_event
        src = event.source.lower()
        et  = event.type

        if et == EventType.LLM_LOADING:
            if "intent" in src:
                self._intent_state = "loading"
            elif "planner" in src:
                self._planner_state = "loading"
            self.refresh()

        elif et == EventType.LLM_LOADED:
            if "intent" in src:
                self._intent_state = "loaded"
            elif "planner" in src:
                self._planner_state = "loaded"
            elif "embed" in src:
                self._embed_state = "loaded"
            self.refresh()

        elif et == EventType.LLM_UNLOADED:
            if "intent" in src:
                self._intent_state = "unloaded"
            elif "planner" in src:
                self._planner_state = "unloaded"
            self.refresh()
