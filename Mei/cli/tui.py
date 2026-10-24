"""
Mei TUI — main agent harness.

Run with:  py -m Mei.cli.tui
Or via:    py app.py

Layout (2x2 grid + input bar):
  ┌─ PIPELINE ──┬─ TRACE ──────────────┐
  │             │                      │
  ├─ MODELS ────┤  (trace spans both   │
  │             │   rows on right)     │
  ├─ MEMORY ────┤                      │
  │             │                      │
  └─────────────┴─ INPUT ──────────────┘

Slash commands:
  /help /teach <name> /done /query <cypher>
  /tools /memory /wipe /restart /status /clear
"""
from __future__ import annotations

import io
import logging
import queue
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Vertical
from textual.message import Message
from textual.widgets import Footer, Header, Input

from ..core.cancellation import get_cancellation_token
from ..core.events import EventType, emit, get_event_bus, subscribe
from .event_bridge import AgentEvent, get_event_bridge
from .widgets import MemoryPane, ModelPane, PipelinePane, TracePane


# ─────────────────────────────────────────────────────────────────────────────
# Print / logging capture
# ─────────────────────────────────────────────────────────────────────────────

class AgentPrint(Message):
    """Carries one complete line of print() or logging output to the TUI."""

    def __init__(self, line: str) -> None:
        super().__init__()
        self.line = line


class TUIPrintCapture(io.TextIOBase):
    """
    Replaces sys.stdout and sys.stderr.

    Buffers partial writes until newline (print() calls write() multiple
    times per line), then posts a complete AgentPrint message.

    Note: llama.cpp writes directly to C-level fd 1/2 — those bypass this
    wrapper entirely. They are silenced via verbose=False in engine.py.
    """

    def __init__(self, app: "MeiTUI") -> None:
        super().__init__()
        self._app = app
        self._buf = ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                self._app.post_message(AgentPrint(line))
        return len(text)

    def flush(self) -> None:
        # Flush any partial line still in buffer
        if self._buf:
            self._app.post_message(AgentPrint(self._buf))
            self._buf = ""

    def fileno(self) -> int:
        # Return original fd so native libraries don't crash on fileno() calls
        return 1


class TUILoggingHandler(logging.Handler):
    """Routes Python logging records into the trace pane."""

    def __init__(self, app: "MeiTUI") -> None:
        super().__init__()
        self._app = app

    def emit(self, record: logging.LogRecord) -> None:  # noqa: A003
        try:
            self._app.post_message(AgentPrint(self.format(record)))
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Main TUI application
# ─────────────────────────────────────────────────────────────────────────────

class MeiTUI(App):
    """Mei agent harness TUI."""

    CSS_PATH = "tui.tcss"
    TITLE = "Mei Agent"
    SUB_TITLE = "v0.1"

    BINDINGS = [
        Binding("escape",  "cancel_execution", "Cancel",      show=True),
        Binding("ctrl+q",  "quit",             "Quit",        show=True),
        Binding("ctrl+l",  "clear_trace",      "Clear trace", show=True),
    ]

    # ── Init ─────────────────────────────────────────────────────────────────

    def __init__(self) -> None:
        super().__init__()
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        self._logging_handler: Optional[TUILoggingHandler] = None

        # Single worker thread — serializes all commands
        self._cmd_queue: queue.Queue = queue.Queue()
        self._worker: Optional[threading.Thread] = None

        # Teaching mode
        self._teaching_name: Optional[str] = None
        self._teaching_steps: list = []
        self._teaching_subscriber = None

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Grid(id="main-grid"):
            yield PipelinePane(id="pipeline-pane")
            yield TracePane(id="trace-pane")
            yield ModelPane(id="model-pane")
            yield MemoryPane(id="memory-pane")
        yield Input(placeholder="> Type a command or /help ...", id="cmd-input")
        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        # Capture stdout/stderr/logging (lightweight, fine on main thread)
        capture = TUIPrintCapture(self)
        sys.stdout = capture
        sys.stderr = capture

        # Tee everything the trace pane shows (plus uncaught exceptions in any
        # thread) into logs/run_<timestamp>.log too — must come AFTER the
        # capture reassignment above, so it wraps TUIPrintCapture rather than
        # being overwritten by it.
        from ..core.run_logger import install_run_logging
        install_run_logging()

        self._logging_handler = TUILoggingHandler(self)
        self._logging_handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
        logging.root.addHandler(self._logging_handler)
        get_event_bridge().attach(self)

        # Gate input during bootstrap
        self.query_one(Input).disabled = True
        self.query_one(TracePane).write(
            "[bold yellow]Bootstrapping agent...[/bold yellow]"
        )

        # Heavy work → Textual worker thread
        self.run_worker(self._bootstrap_and_start, thread=True, exclusive=True)

    def _bootstrap_and_start(self) -> None:
        """Runs on a worker thread — all heavy imports and init happen here."""
        self._bootstrap_agent()
        self._start_worker()
        # Re-enable input from the main thread
        self.call_from_thread(self._on_bootstrap_complete)

    def _on_bootstrap_complete(self) -> None:
        self.query_one(Input).disabled = False
        self.query_one(TracePane).write(
            "[bold green]Mei TUI ready.[/bold green]  Type a command or [bold]/help[/bold]"
        )

    def on_unmount(self) -> None:
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr
        if self._logging_handler:
            logging.root.removeHandler(self._logging_handler)
        self._cmd_queue.put(None)  # shutdown signal to worker

    def _bootstrap_agent(self) -> None:
        from ..action.executor import get_executor
        from ..core.config import init_config
        from ..core.pipeline import start_pipeline
        from ..memory.working import get_working_memory
        from ..memory.graph import init_graph

        init_config()
        init_graph()
        get_working_memory()
        get_executor()
        emit(EventType.AGENT_STARTED, source="MeiTUI")
        start_pipeline()

    # ── AgentEvent routing ────────────────────────────────────────────────────

    def on_agent_event(self, msg: AgentEvent) -> None:
        """
        Route agent events to each pane explicitly.
        Textual messages bubble UP the DOM, not down — so the App handles
        AgentEvent and dispatches to widgets directly.
        """
        self.query_one(PipelinePane).on_agent_event(msg)
        self.query_one(TracePane).on_agent_event(msg)
        self.query_one(ModelPane).on_agent_event(msg)
        self.query_one(MemoryPane).on_agent_event(msg)

    def on_agent_print(self, msg: AgentPrint) -> None:
        try:
            self.query_one(TracePane).write_agent_print(msg.line)
        except Exception:
            pass

    # ── Worker thread ─────────────────────────────────────────────────────────

    def _start_worker(self) -> None:
        self._worker = threading.Thread(
            target=self._agent_worker, daemon=True, name="MeiWorker"
        )
        self._worker.start()

    def _agent_worker(self) -> None:
        """
        Single long-lived worker — serializes all commands.
        Catches every exception to keep the TUI alive.
        """
        import time as _time

        from ..action.context import ExecutionContext
        from ..core.pipeline import process_user_command
        from ..memory.graph.episodic import write_episode
        from ..memory.working import get_working_memory

        while True:
            cmd = self._cmd_queue.get()
            if cmd is None:
                break  # shutdown

            # ── Teaching save sentinel ────────────────────────────────────
            if isinstance(cmd, tuple) and cmd[0] == "__teach_save__":
                _, name, steps = cmd
                try:
                    from ..memory.graph.stability import score_episode
                    stability_score = score_episode(steps)
                    write_episode(
                        execution_id=f"teach_{int(_time.time() * 1000)}",
                        session_id=get_working_memory()._session_id or "teach",
                        intent={
                            "raw_command": name,
                            "action": "taught",
                            "target": None,
                        },
                        step_results=[
                            {
                                "action": s["action"],
                                "parameters": s["parameters"],
                                "success": True,
                                "duration_ms": 0,
                                "data": {},
                                "method_used": "taught",
                                "step_description": s["action"],
                                "step_domain": "taught",
                                "step_expected_output": "",
                            }
                            for s in steps
                        ],
                        success=True,
                        duration_ms=0,
                        stability_score=stability_score,
                    )
                    emit(
                        EventType.MEMORY_STORED,
                        source="Teaching",
                        name=name,
                        steps=len(steps),
                    )
                except Exception as e:
                    emit(EventType.ERROR, source="Teaching", error=str(e))
                continue

            # ── Regular command ───────────────────────────────────────────
            try:
                from ..action.executor import get_executor
                executor = get_executor()
                get_cancellation_token().reset()
                
                ctx = getattr(executor, '_current_context', None)
                if not ctx:
                    ctx = ExecutionContext.empty()
                    sid = get_working_memory()._session_id
                    if sid:
                        ctx.set_variable("session_id", sid)
                    executor._current_context = ctx
                    
                process_user_command(cmd, ctx)
            except Exception:
                emit(EventType.ERROR, source="Worker", error=traceback.format_exc())
                # Worker stays alive — ready for next command

    # ── Input handling ────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        if text.startswith("/"):
            self._handle_slash(text)
        else:
            if self._worker and not self._worker.is_alive():
                self._show_error("Worker crashed — use [bold]/restart[/bold] to recover.")
                return
            self._cmd_queue.put(text)

    def _handle_slash(self, cmd: str) -> None:
        trace = self.query_one(TracePane)
        parts = cmd.split(None, 1)
        verb  = parts[0].lower()
        arg   = parts[1] if len(parts) > 1 else ""

        if verb == "/help":
            trace.write(
                "[bold]Commands:[/bold]\n"
                "  /teach [name]   Start recording a workflow\n"
                "  /done           Stop recording and save\n"
                "  /query [cypher] Run a Kùzu query (live)\n"
                "  /tools          List registered tools\n"
                "  /memory         Show memory stats\n"
                "  /graph          Export memory graph to HTML and open it\n"
                "  /wipe           Wipe the Kùzu database\n"
                "  /restart        Restart the agent worker\n"
                "  /clear          Clear this trace pane\n"
                "  Esc             Cancel current execution\n"
                "  Ctrl+Q          Quit"
            )

        elif verb == "/teach":
            if not arg:
                trace.write("[red]Usage: /teach <workflow name>[/red]")
            elif self._teaching_name is not None:
                trace.write(
                    f"[yellow]Already recording [bold]{self._teaching_name!r}[/bold]. "
                    "Use /done first.[/yellow]"
                )
            else:
                self._start_teaching(arg)

        elif verb == "/done":
            if self._teaching_name is None:
                trace.write("[yellow]/done — not currently recording.[/yellow]")
            elif not self._teaching_steps:
                trace.write("[yellow]No steps recorded yet. Demonstrate actions first.[/yellow]")
            else:
                name  = self._teaching_name
                steps = list(self._teaching_steps)
                self._stop_teaching()
                self._confirm_teach_save(name, steps)

        elif verb == "/query":
            if not arg:
                trace.write("[red]Usage: /query <cypher>[/red]")
            else:
                self._run_query(arg)

        elif verb == "/tools":
            from ..action.executor import get_executor
            tools = get_executor().list_actions()
            trace.write("[bold]Tools:[/bold]  " + "  ".join(tools))

        elif verb == "/memory":
            self._show_memory_stats()

        elif verb == "/wipe":
            self._confirm_wipe()

        elif verb == "/restart":
            self._restart_worker()
            
        elif verb == "/graph":
            try:
                from .graph_export import export_graph
                path = export_graph()
                trace.write(f"[bold green]Graph exported and opened:[/bold green] {path}")
            except Exception as e:
                trace.write(f"[bold red]Failed to export graph:[/bold red] {e}")

        elif verb in ("/clear", "/cl"):
            trace.clear()

        elif verb in ("/status", "/refresh"):
            pass  # panes update from events; this is informational only

        else:
            trace.write(
                f"[red]Unknown command: {cmd}[/red]  "
                "Type [bold]/help[/bold] for a list."
            )

    # ── Teaching mode ─────────────────────────────────────────────────────────

    def _start_teaching(self, name: str) -> None:
        self._teaching_name  = name
        self._teaching_steps = []

        def _capture(event) -> None:
            self._teaching_steps.append({
                "action":     event.data.get("action"),
                "parameters": event.data.get("parameters", {}),
            })

        self._teaching_subscriber = _capture
        subscribe(EventType.PLAN_STEP_COMPLETED, _capture)

        self.query_one(TracePane).write(
            f"[yellow bold]● REC[/yellow bold]  Recording [bold]{name!r}[/bold] — "
            "demonstrate the workflow, then type [bold]/done[/bold]"
        )

    def _stop_teaching(self) -> None:
        if self._teaching_subscriber is not None:
            get_event_bus().unsubscribe(
                EventType.PLAN_STEP_COMPLETED, self._teaching_subscriber
            )
            self._teaching_subscriber = None
        self._teaching_name  = None
        self._teaching_steps = []

    def _confirm_teach_save(self, name: str, steps: list) -> None:
        """Show the captured steps before committing them to memory — a
        recorded episode should not silently become a trusted, replayable
        procedure without the user seeing what was actually captured."""
        from textual.screen import ModalScreen
        from textual.widgets import Button, Label, Static
        from rich.markup import escape

        lines = [f"{i+1}. {s.get('action')}({s.get('parameters', {})})" for i, s in enumerate(steps)]
        preview = "\n".join(escape(line) for line in lines[:12])
        if len(lines) > 12:
            preview += f"\n... and {len(lines) - 12} more"

        class TeachConfirm(ModalScreen):
            CSS = """
            TeachConfirm { align: center middle; }
            #dialog {
                background: $surface;
                border: thick $accent;
                padding: 2 4;
                width: 72;
                height: auto;
            }
            #q { margin-bottom: 1; }
            #steps { margin-bottom: 1; color: $text-muted; }
            """

            def compose(self) -> ComposeResult:
                with Vertical(id="dialog"):
                    yield Label(f"Save workflow [bold]{escape(name)!r}[/bold] "
                                f"with {len(steps)} step(s)?", id="q")
                    yield Static(preview or "(no steps)", id="steps")
                    yield Button("Save", variant="success", id="yes")
                    yield Button("Discard", variant="error", id="no")

            def on_button_pressed(self, event: Button.Pressed) -> None:
                self.dismiss(event.button.id == "yes")

        def _after(confirmed: bool) -> None:
            trace = self.query_one(TracePane)
            if confirmed:
                self._cmd_queue.put(("__teach_save__", name, steps))
                trace.write(f"[green]Saving [bold]{name!r}[/bold] with {len(steps)} step(s)...[/green]")
            else:
                trace.write(f"[yellow]Discarded recording [bold]{name!r}[/bold].[/yellow]")

        self.push_screen(TeachConfirm(), _after)
        self._teaching_name  = None
        self._teaching_steps = []

    # ── Live Kùzu query ───────────────────────────────────────────────────────

    def _run_query(self, cypher: str) -> None:
        trace = self.query_one(TracePane)
        try:
            from rich.markup import escape
            from rich.table import Table

            from ..memory.graph.connection import get_kuzu_connection

            rows = get_kuzu_connection().execute(cypher)
            if not rows:
                trace.write("[dim](no results)[/dim]")
                return

            table = Table(show_header=True, header_style="bold cyan", box=None)
            for col in rows[0].keys():
                table.add_column(str(col))
            for row in rows[:50]:
                table.add_row(*[escape(str(v)) for v in row.values()])
            trace.write(table)
        except Exception as e:
            trace.write(f"[red]Query error: {e}[/red]")

    # ── Memory stats ──────────────────────────────────────────────────────────

    def _show_memory_stats(self) -> None:
        trace = self.query_one(TracePane)
        try:
            from ..memory.graph.connection import get_kuzu_connection

            conn  = get_kuzu_connection()
            stats = {}
            for tbl, label in [
                ("Goal",         "Goals"),
                ("Action",       "Actions"),
                ("Session",      "Sessions"),
                ("ElementCache", "Elements"),
                ("Preference",   "Preferences"),
            ]:
                try:
                    r = conn.execute(f"MATCH (n:{tbl}) RETURN count(n) AS c")
                    stats[label] = r[0]["c"] if r else 0
                except Exception:
                    stats[label] = "?"
            line = "  ".join(f"[bold]{v}[/bold] {k}" for k, v in stats.items())
            trace.write(f"[cyan]Memory:[/cyan]  {line}")
        except Exception as e:
            trace.write(f"[red]Memory stats error: {e}[/red]")

    # ── /wipe ─────────────────────────────────────────────────────────────────

    def _confirm_wipe(self) -> None:
        from textual.screen import ModalScreen
        from textual.widgets import Button, Label

        class WipeConfirm(ModalScreen):
            CSS = """
            WipeConfirm { align: center middle; }
            #dialog {
                background: $surface;
                border: thick $error;
                padding: 2 4;
                width: 52;
                height: auto;
            }
            #q { margin-bottom: 1; text-align: center; }
            """

            def compose(self) -> ComposeResult:
                with Vertical(id="dialog"):
                    yield Label(
                        "⚠  Wipe the entire Kùzu database?\nThis cannot be undone.",
                        id="q",
                    )
                    yield Button("Yes, wipe", variant="error",   id="yes")
                    yield Button("Cancel",    variant="primary",  id="no")

            def on_button_pressed(self, event: Button.Pressed) -> None:
                self.dismiss(event.button.id == "yes")

        def _after(confirmed: bool) -> None:
            if confirmed:
                self._do_wipe()

        self.push_screen(WipeConfirm(), _after)

    def _do_wipe(self) -> None:
        trace = self.query_one(TracePane)

        # 1. Signal cancel
        get_cancellation_token().cancel()

        # 2. Stop worker — clear queue first, then send sentinel
        if self._worker and self._worker.is_alive():
            try:
                while True:
                    self._cmd_queue.get_nowait()
            except queue.Empty:
                pass
            self._cmd_queue.put(None)
            self._worker.join(timeout=1.0)

            if self._worker.is_alive():
                trace.write(
                    "[red]Worker still running (stuck in LLM call).[/red]  "
                    "Press [bold]Esc[/bold] to cancel first, then retry [bold]/wipe[/bold]."
                )
                return

        # 3. Release Kùzu singleton (Database holds the file lock)
        try:
            import Mei.memory.graph.connection as _conn_mod
            _conn_mod._instance = None
            import gc
            gc.collect()
        except Exception as e:
            trace.write(f"[yellow]Warning: Kùzu close: {e}[/yellow]")

        # 4. Delete DB directory
        from ..core.config import get_config

        db_path = Path(get_config().kuzu.database_path)
        try:
            shutil.rmtree(db_path, ignore_errors=True)
            trace.write(f"[green]Wiped {db_path}[/green]")
        except Exception as e:
            trace.write(f"[red]Delete failed: {e}[/red]")
            return

        # 5. Re-bootstrap schema
        try:
            import Mei.memory.graph as _graph_mod
            # init_graph() no-ops once bootstrapped — reset so the schema is re-applied
            _graph_mod._bootstrapped = False
            _graph_mod.init_graph()
            if not _graph_mod._bootstrapped:
                raise RuntimeError("init_graph() did not complete (see console)")
            trace.write("[green]Kùzu re-initialized.[/green]")
        except Exception as e:
            trace.write(f"[red]Re-bootstrap failed: {e}[/red]")

        # 6. Fresh worker
        self._start_worker()

    # ── /restart ──────────────────────────────────────────────────────────────

    def _restart_worker(self) -> None:
        trace = self.query_one(TracePane)
        if self._worker and self._worker.is_alive():
            trace.write(
                "[yellow]Worker still running.[/yellow]  "
                "Press [bold]Esc[/bold] to cancel, then retry [bold]/restart[/bold]."
            )
            return
        trace.write("[cyan]Restarting agent worker...[/cyan]")
        self._start_worker()
        trace.write("[green]Worker restarted.[/green]")

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_cancel_execution(self) -> None:
        """Escape — soft-cancel current execution."""
        get_cancellation_token().cancel()
        self.query_one(PipelinePane)._status = "CANCELLING"
        self.query_one(PipelinePane).refresh()
        self.query_one(TracePane).write("[yellow]◼ Cancelling...[/yellow]")

    def action_clear_trace(self) -> None:
        self.query_one(TracePane).clear()

    def _show_error(self, msg: str) -> None:
        try:
            self.query_one(TracePane).write(f"[red]{msg}[/red]")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    MeiTUI().run()


if __name__ == "__main__":
    main()
