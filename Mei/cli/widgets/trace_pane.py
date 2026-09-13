"""
Trace pane — live execution log with step status icons.

Updates on:
  PLAN_STEP_COMPLETED, PLAN_STEP_FAILED, PLAN_COMPLETED, PLAN_FAILED,
  MEMORY_PLAN_FOUND, MEMORY_PLAN_NOT_FOUND, TRANSCRIBE_COMPLETED,
  LLM_LOADING, LLM_LOADED, ERROR.

Uses rich.markup.escape on ALL user-derived text to prevent markup injection.
Called directly by MeiTUI.on_agent_event — not through Textual dispatch.
"""
from rich.markup import escape
from textual.widgets import RichLog

from ...core.events import EventType
from ..event_bridge import AgentEvent


class TracePane(RichLog):
    """Scrollable rich log of agent execution events."""

    DEFAULT_CSS = """
    TracePane {
        height: 100%;
    }
    """

    def on_mount(self) -> None:
        self.border_title = "EXECUTION TRACE"
        self.highlight = True
        self.markup = True

    def on_agent_event(self, msg: AgentEvent) -> None:
        """Called directly by MeiTUI.on_agent_event."""
        event = msg.agent_event
        et = event.type
        data = event.data

        if et == EventType.TRANSCRIBE_COMPLETED:
            text = escape(data.get("text", ""))
            self.write(f"\n[bold cyan]> Command:[/bold cyan] {text}")

        elif et == EventType.MEMORY_PLAN_FOUND:
            tier = data.get("tier", "?")
            conf = data.get("confidence", 0.0)
            stab = data.get("stability_score", "-")
            self.write(
                f"[blue]  MemoryHit tier={tier} conf={conf:.4f} stab={stab}[/blue]"
            )

        elif et == EventType.MEMORY_PLAN_NOT_FOUND:
            self.write("[dim]  No memory match - decomposing fresh[/dim]")

        elif et == EventType.PLAN_STEP_COMPLETED:
            action = escape(str(data.get("action", "")))
            params = escape(str(data.get("parameters", {})))
            method = escape(str(data.get("method_used", "")))
            self.write(
                f"  [green]*[/green] [bold]{action}[/bold]"
                f"  [dim]{params}[/dim]  [dim]{method}[/dim]"
            )

        elif et == EventType.PLAN_STEP_FAILED:
            action = escape(str(data.get("action", "")))
            error  = escape(str(data.get("error", "")))
            self.write(f"  [red]x[/red] [bold]{action}[/bold]  [red]{error}[/red]")

        elif et == EventType.PLAN_COMPLETED:
            dur = data.get("duration_ms", 0)
            self.write(
                f"[green bold]* PLAN COMPLETED[/green bold]  [dim]{dur:.0f}ms[/dim]"
            )

        elif et == EventType.PLAN_FAILED:
            reason = data.get("reason", "")
            if reason == "cancelled":
                self.write("[dim][] Cancelled by user[/dim]")
            else:
                err = escape(str(reason or data.get("error", "unknown")))
                self.write(f"[red bold]x PLAN FAILED[/red bold]  [red]{err}[/red]")

        elif et == EventType.LLM_LOADING:
            src = escape(str(event.source))
            self.write(f"[yellow]  @ Loading model [{src}]...[/yellow]")

        elif et == EventType.LLM_LOADED:
            src = escape(str(event.source))
            self.write(f"[green]  * Model loaded [{src}][/green]")

        elif et == EventType.ERROR:
            src = escape(str(event.source))
            err = escape(str(data.get("error", "")))
            self.write(f"[red bold]! ERROR[/red bold] [{src}] {err}")

    def write_agent_print(self, text: str) -> None:
        """Route print()/logging output from agent threads into the trace."""
        self.write(f"[dim]{escape(text)}[/dim]")
