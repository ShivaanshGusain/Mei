"""
Mei Graph Inspector — standalone read-only Kùzu viewer.

Run with:  py -m Mei.cli.graph

POST-MORTEM tool only. Opens Kùzu in read-only mode.
While the agent is running and holds the write lock, shows a
"DB locked" banner. Press r to retry.

For live inspection while the agent is running, use /query inside the TUI.

Keybindings:
  r     Reopen DB, rebuild goal tree, refresh stats
  F5    Execute the Cypher in the query panel
  Ctrl+Q  Quit
"""
from __future__ import annotations

import json
from typing import Optional

import kuzu
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Static, TextArea, Tree


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _db_path() -> str:
    """Pull DB path from shared config, never a hardcoded string."""
    try:
        from ..core.config import get_config
        return get_config().kuzu.database_path
    except Exception:
        return "data/kuzu_memory"


def _open_readonly() -> Optional[kuzu.Connection]:
    """
    Open a fresh read-only Database + Connection.
    Returns None if the agent holds the write lock.
    Callers must store the Database reference to keep the lock alive.
    """
    try:
        db   = kuzu.Database(_db_path(), read_only=True)
        conn = kuzu.Connection(db)
        return conn, db
    except Exception as e:
        msg = str(e).lower()
        if "lock" in msg or "cannot set lock" in msg:
            return None, None
        raise


STARTER_QUERIES = [
    "MATCH (g:Goal)\nRETURN g.raw_command, g.stability_score, g.created_at\nORDER BY g.created_at DESC LIMIT 20",
    "MATCH (g:Goal)-[:ACHIEVED_BY]->(a:Action)\nRETURN g.raw_command, count(a) AS steps\nORDER BY steps DESC LIMIT 20",
    "MATCH (p:Preference)\nRETURN p.pref_key, p.pref_value, p.category\nORDER BY p.category",
    "MATCH (e:ElementCache)\nRETURN e.element_query, e.app_name, e.hit_count\nORDER BY e.hit_count DESC LIMIT 20",
    "MATCH (s:Session)\nRETURN s.id, s.started_at, s.ended_at\nORDER BY s.started_at DESC LIMIT 10",
]


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

class MeiGraph(App):
    """Standalone Kùzu graph inspector."""

    TITLE = "Mei Graph Inspector"
    SUB_TITLE = _db_path()

    BINDINGS = [
        Binding("r",      "refresh",   "Refresh",   show=True),
        Binding("f5",     "run_query", "Run query", show=True),
        Binding("ctrl+q", "quit",      "Quit",      show=True),
    ]

    CSS = """
    Screen { layout: vertical; }

    #top-row {
        height: 1fr;
        layout: horizontal;
    }

    #goal-tree {
        width: 40%;
        border: solid $primary;
    }

    #right-col {
        width: 60%;
        layout: vertical;
    }

    #query-area {
        height: 8;
        border: solid $accent;
    }

    #results-table {
        height: 1fr;
        border: solid $primary;
    }

    #stats-bar {
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._conn: Optional[kuzu.Connection] = None
        self._db:   Optional[kuzu.Database]   = None  # must hold ref to keep lock
        self._locked = False

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top-row"):
            yield Tree("Goals (press r to load)", id="goal-tree")
            with Vertical(id="right-col"):
                yield TextArea(STARTER_QUERIES[0], id="query-area")
                yield DataTable(id="results-table")
        yield Static("", id="stats-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(DataTable).show_header = True
        self.action_refresh()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        """[r] Close previous DB, reopen read-only, rebuild tree + stats."""
        # Release previous Database object (this drops the read-only lock)
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None
        self._db   = None

        self._conn, self._db = _open_readonly()
        stats_bar = self.query_one("#stats-bar", Static)

        if self._conn is None:
            self._locked = True
            stats_bar.update(
                "⚠  DB locked — agent is running.  "
                "Press [bold]r[/bold] to retry, or use [bold]/query[/bold] inside the TUI."
            )
            tree = self.query_one("#goal-tree", Tree)
            tree.clear()
            tree.root.add_leaf("(DB locked — agent holds write lock)")
            return

        self._locked = False
        self._rebuild_tree()
        self._refresh_stats()

    def _rebuild_tree(self) -> None:
        if self._conn is None:
            return

        tree = self.query_one("#goal-tree", Tree)
        tree.clear()

        try:
            rows = self._conn.execute("""
                MATCH (g:Goal)
                OPTIONAL MATCH (g)-[:ACHIEVED_BY]->(first:Action)
                OPTIONAL MATCH p = (first)-[:NEXT_ACTION*0..20]->(a:Action)
                RETURN DISTINCT
                    g.id AS gid,
                    g.raw_command AS cmd,
                    g.stability_score AS stab,
                    g.created_at AS ts,
                    a.tool_name AS tool,
                    a.parameters_json AS params,
                    a.step_domain AS domain
                ORDER BY g.created_at DESC, length(p)
                LIMIT 100
            """)
        except Exception as e:
            tree.root.add_leaf(f"Query error: {e}")
            return

        # Group rows by goal id
        goals: dict[str, dict] = {}
        goal_actions: dict[str, list] = {}

        for row in rows:
            gid = row.get("gid", "?")
            if gid not in goals:
                stab = row.get("stab")
                goals[gid] = {
                    "cmd":  (row.get("cmd") or "")[:60],
                    "stab": f"{stab:.2f}" if stab is not None else "?",
                    "ts":   (row.get("ts") or "")[:19],
                }
                goal_actions[gid] = []

            tool = row.get("tool")
            if tool:
                try:
                    params = json.loads(row.get("params") or "{}")
                except Exception:
                    params = {}
                goal_actions[gid].append(
                    (tool, params, row.get("domain", ""))
                )

        root = tree.root
        for gid, meta in goals.items():
            label = (
                f"{meta['cmd']}  "
                f"[dim]stab={meta['stab']}  {meta['ts']}[/dim]"
            )
            node = root.add(label, expand=False)
            seen: set = set()
            for tool, params, domain in goal_actions.get(gid, []):
                key = (tool, json.dumps(params, sort_keys=True))
                if key in seen:
                    continue
                seen.add(key)
                pstr = ", ".join(
                    f"{k}={v!r}" for k, v in list(params.items())[:3]
                )
                node.add_leaf(f"[dim][{domain}][/dim] {tool}({pstr})")

    def _refresh_stats(self) -> None:
        if self._conn is None:
            return

        stats_bar = self.query_one("#stats-bar", Static)
        counts: dict[str, object] = {}
        for tbl, label in [
            ("Goal",         "Goals"),
            ("Action",       "Actions"),
            ("Session",      "Sessions"),
            ("ElementCache", "Elements"),
            ("Preference",   "Preferences"),
        ]:
            try:
                r = self._conn.execute(
                    f"MATCH (n:{tbl}) RETURN count(n) AS c"
                )
                counts[label] = r[0]["c"] if r else 0
            except Exception:
                counts[label] = "?"

        summary = "  │  ".join(f"{label}: {v}" for label, v in counts.items())
        stats_bar.update(
            f"  {summary}"
            "  │  [r] refresh  [F5] run query  [Ctrl+Q] quit"
        )

    # ── Query panel ───────────────────────────────────────────────────────────

    def action_run_query(self) -> None:
        """[F5] Execute Cypher from the query text area."""
        if self._locked or self._conn is None:
            self.query_one("#stats-bar", Static).update(
                "⚠  DB locked. Press [r] to retry."
            )
            return

        cypher = self.query_one("#query-area", TextArea).text.strip()
        if not cypher:
            return

        tbl = self.query_one("#results-table", DataTable)
        tbl.clear(columns=True)

        try:
            rows = self._conn.execute(cypher)
        except Exception as e:
            tbl.add_columns("Error")
            tbl.add_row(str(e))
            return

        if not rows:
            tbl.add_columns("Result")
            tbl.add_row("(no results)")
            return

        cols = list(rows[0].keys())
        tbl.add_columns(*[str(c) for c in cols])
        for row in rows[:200]:
            tbl.add_row(*[str(row.get(c, "")) for c in cols])


# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    MeiGraph().run()


if __name__ == "__main__":
    main()
