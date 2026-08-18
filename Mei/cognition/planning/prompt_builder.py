from typing import Any
import numpy as np

from ...core.task import IntentStep
from ...action.context import ExecutionContext

# ─────────────────────────────────────────────────────────────────────────────
# TOOL_REGISTRY  — one-line descriptions, used for embedding & similarity search
# ─────────────────────────────────────────────────────────────────────────────
TOOL_REGISTRY = {
    "launch_app":               "Launch or focus an application by name",
    "terminate_app":            "Terminate a running application by name or PID",
    "find_window":              "Find an open window by title or handle",
    "verify_window":            "Wait for a window to appear after launching an app",
    "focus_window":             "Bring a window to the foreground",
    "minimize_window":          "Minimize a window",
    "maximize_window":          "Maximize a window",
    "restore_window":           "Restore a minimized or maximized window",
    "close_window":             "Close a window",
    "find_element":             "Find and cache a UI element without clicking it",
    "type_text":                "Type text into current focus or a specific UI element",
    "hotkey":                   "Press a keyboard shortcut combination",
    "click":                    "Click a UI element by name or at screen coordinates",
    "scroll":                   "Scroll the mouse wheel up or down",
    "web_navigate":             "Navigate to a URL in the browser via Playwright CDP",
    "web_click":                "Click a web page element by text, role, CSS selector",
    "web_type":                 "Type text into a web page input field via Playwright",
    "web_get_state":            "Get current web page content, links, or inputs",
    "web_wait_for":             "Wait for a web element to become visible or hidden",
    "web_scroll":               "Scroll the web page up or down via Playwright",
    "navigate_url":             "Open a URL in the native browser window via keyboard",
    "run_shell_command":        "Run a shell command and return stdout and stderr",
    "start_background_process": "Start a long-running background process, returns PID",
    "get_process_logs":         "Read recent output from a managed background process",
    "kill_process":             "Terminate a managed background process by PID",
    "list_files":               "List files and folders in a directory",
    "read_file":                "Read file contents by line range with line numbers",
    "search_files":             "Search for text or regex pattern in files under a directory",
    "create_file_or_folder":    "Create a new file or directory at a given path. PREFER over launching a text editor.",
    "write_to_file":            "Write or append content to a file",
    "edit_file_by_lines":       "Replace a range of lines in a file",
    "delete_path":              "Send a file or folder to Recycle Bin, confirm must be true",
    "rename_or_move":           "Rename or move a file or folder",
    "download_file":            "Download a file from a URL to a local path",
    "change_directory":         "Change the working directory for subsequent shell commands",
    "get_cwd":                  "Get the current working directory",
    "get_system_info":          "Get OS, CPU, memory, and disk usage info",
    "wait":                     "Pause execution, use after launching apps before interacting",
}

# ─────────────────────────────────────────────────────────────────────────────
# TOOL_DETAIL  — full param signatures, injected into the prompt mini-catalog
# ─────────────────────────────────────────────────────────────────────────────
TOOL_DETAIL = {
    "launch_app": (
        'launch_app(app_name: str)\n'
        '  Launch or focus an application.'
    ),
    "terminate_app": (
        'terminate_app(app_name: str | pid: int)\n'
        '  Kill a running application.'
    ),
    "find_window": (
        'find_window(title: str | hwnd: int)\n'
        '  Find an open window by title or handle.'
    ),
    "verify_window": (
        'verify_window(title: str, timeout?: float)\n'
        '  Wait for a window to appear (use after launching apps).'
    ),
    "focus_window": (
        'focus_window(query: str | hwnd: int)\n'
        '  Bring a window to the foreground.'
    ),
    "minimize_window": (
        'minimize_window(query?: str | hwnd?: int)\n'
        '  Minimize a window. Empty = current window.'
    ),
    "maximize_window": (
        'maximize_window(query?: str | hwnd?: int)\n'
        '  Maximize a window.'
    ),
    "restore_window": (
        'restore_window(query?: str | hwnd?: int)\n'
        '  Restore a minimized/maximized window.'
    ),
    "close_window": (
        'close_window(query?: str | hwnd?: int)\n'
        '  Close a window.'
    ),
    "find_element": (
        'find_element(query: str, element_type?: str, timeout?: float, cache_as?: str)\n'
        '  Find and cache a UI element without clicking it.'
    ),
    "type_text": (
        'type_text(text: str, element_query?: str, clear_first?: bool, interval?: float)\n'
        '  Type text into current focus or a specific UI element.'
    ),
    "hotkey": (
        'hotkey(keys: list[str], presses?: int, hold_time?: float)\n'
        '  Press a keyboard shortcut. Example: ["ctrl", "c"]'
    ),
    "click": (
        'click(query: str | x: int + y: int, click_type?: "left"|"right"|"double")\n'
        '  Click a UI element by name or at screen coordinates.'
    ),
    "scroll": (
        'scroll(direction: "up"|"down", amount?: int, x?: int, y?: int)\n'
        '  Scroll the mouse wheel.'
    ),
    "web_navigate": (
        'web_navigate(url: str, new_tab?: bool)\n'
        '  Navigate to a URL in the browser via Playwright. Requires CDP on port 9222.'
    ),
    "web_click": (
        'web_click(selector: str, selector_type?: "text"|"role"|"placeholder"|"label"|"css"|"xpath"|"testid")\n'
        '  Click a web page element.'
    ),
    "web_type": (
        'web_type(selector: str, text: str, selector_type?: str, clear_first?: bool, submit?: bool)\n'
        '  Type into a web page input field.'
    ),
    "web_get_state": (
        'web_get_state(extract_type?: "text"|"html"|"links"|"inputs"|"structured")\n'
        '  Get current page content, links, or inputs.'
    ),
    "web_wait_for": (
        'web_wait_for(selector: str, selector_type?: str, state?: "visible"|"hidden", timeout_ms?: int)\n'
        '  Wait for a web element to reach a state.'
    ),
    "web_scroll": (
        'web_scroll(direction: "up"|"down", amount?: int)\n'
        '  Scroll the web page.'
    ),
    "navigate_url": (
        'navigate_url(url: str, new_tab?: bool)\n'
        '  Open a URL using the existing native browser window via keyboard. No CDP required.'
    ),
    "run_shell_command": (
        'run_shell_command(command: str, timeout?: int)\n'
        '  Run a shell command, returns stdout/stderr.'
    ),
    "start_background_process": (
        'start_background_process(command: str)\n'
        '  Start a long-running process in the background. Returns PID.'
    ),
    "get_process_logs": (
        'get_process_logs(pid: int, lines?: int)\n'
        '  Read recent output from a background process.'
    ),
    "kill_process": (
        'kill_process(pid: int)\n'
        '  Terminate a managed background process.'
    ),
    "list_files": (
        'list_files(path: str, recursive?: bool, show_hidden?: bool)\n'
        '  List files and folders in a directory.'
    ),
    "read_file": (
        'read_file(path: str, start_line?: int, max_lines?: int, tail?: bool)\n'
        '  Read file contents with line numbers.'
    ),
    "search_files": (
        'search_files(directory: str, pattern: str, file_glob?: str, is_regex?: bool)\n'
        '  Search for text or regex in files under a directory.'
    ),
    "create_file_or_folder": (
        'create_file_or_folder(path: str, is_dir?: bool, content?: str)\n'
        '  Create a new file or directory. PREFER over launching a text editor. Use full absolute path.'
    ),
    "write_to_file": (
        'write_to_file(path: str, content: str, mode?: "write"|"append"|"overwrite")\n'
        '  Write or append content to a file.'
    ),
    "edit_file_by_lines": (
        'edit_file_by_lines(path: str, start_line: int, end_line: int, new_content: str)\n'
        '  Replace a range of lines in a file. Use read_file first to see line numbers.'
    ),
    "delete_path": (
        'delete_path(path: str, confirm: bool)\n'
        '  Send a file or folder to Recycle Bin. confirm must be true.'
    ),
    "rename_or_move": (
        'rename_or_move(source: str, destination: str)\n'
        '  Rename or move a file or folder.'
    ),
    "download_file": (
        'download_file(url: str, destination: str)\n'
        '  Download a file from a URL to a local path.'
    ),
    "change_directory": (
        'change_directory(path: str)\n'
        '  Change the working directory for subsequent shell commands.'
    ),
    "get_cwd": (
        'get_cwd()\n'
        '  Get the current working directory.'
    ),
    "get_system_info": (
        'get_system_info()\n'
        '  Get OS, CPU, memory, and disk usage info.'
    ),
    "wait": (
        'wait(seconds: float, reason?: str)\n'
        '  Pause execution. Use after launching apps before interacting.'
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# DOMAIN_ANCHOR  — guaranteed tool per domain regardless of similarity score
# ─────────────────────────────────────────────────────────────────────────────
DOMAIN_ANCHOR = {
    "app":     "launch_app",
    "window":  "focus_window",
    "web":     "web_navigate",
    "input":   "type_text",
    "file":    "create_file_or_folder",
    "system":  "run_shell_command",
    "utility": "wait",
}

# ─────────────────────────────────────────────────────────────────────────────
# Tool embedding cache  — populated once on first call to _embed_tools()
# ─────────────────────────────────────────────────────────────────────────────
_tool_embeddings: dict = {}


def _embed_tools() -> None:
    """Lazy init — embeds all tool descriptions once and caches them."""
    global _tool_embeddings
    if _tool_embeddings:
        return
    try:
        from ...memory.graph.embedder import embed
        print("[PromptBuilder] Embedding tool descriptions...")
        for name, desc in TOOL_REGISTRY.items():
            _tool_embeddings[name] = embed(f"{name}: {desc}")
        print(f"[PromptBuilder] {len(_tool_embeddings)} tool embeddings ready.")
    except Exception as e:
        print(f"[PromptBuilder] Failed to embed tools: {e}")


def _retrieve_tools(step_description: str, domain: str, top_k: int = 5) -> list:
    """
    Embed step_description and return the top_k most relevant tool names
    by cosine similarity, with the domain anchor always at position 0.
    """
    _embed_tools()

    if not _tool_embeddings:
        # Fallback: return anchor + a few defaults if embedding failed
        anchor = DOMAIN_ANCHOR.get(domain, "wait")
        return [anchor]

    try:
        from ...memory.graph.embedder import embed
        query_emb = np.array(embed(step_description))

        scores = {}
        for name, emb in _tool_embeddings.items():
            b = np.array(emb)
            scores[name] = float(
                np.dot(query_emb, b) /
                (np.linalg.norm(query_emb) * np.linalg.norm(b) + 1e-9)
            )

        ranked = sorted(scores, key=scores.get, reverse=True)[:top_k]

        # Enforce domain anchor at front
        anchor = DOMAIN_ANCHOR.get(domain)
        if anchor:
            if anchor in ranked:
                ranked = [anchor] + [t for t in ranked if t != anchor]
            else:
                ranked = [anchor] + ranked[:top_k - 1]

        return ranked

    except Exception as e:
        print(f"[PromptBuilder] _retrieve_tools failed: {e}")
        anchor = DOMAIN_ANCHOR.get(domain, "wait")
        return [anchor]


# ─────────────────────────────────────────────────────────────────────────────
# build_step_prompt  — returns (prompt_str, retrieved_tool_names)
# ─────────────────────────────────────────────────────────────────────────────

def _get_env_state(step: IntentStep, context: ExecutionContext) -> str:
      """
      Inject domain-specific environment state into the prompt.
      - system/file: cwd + directory listing + allowed write roots
      - app: running processes matching the step target
      - web/window/input/utility: no injection
      """
      import os
      from pathlib import Path
      domain = step.domain
      lines = []

      if domain in ("system", "file"):
          try:
              # Use agent's virtual cwd, not the process cwd
              cwd = context.get_variable("cwd") or os.getcwd()
              try:
                  entries = [
                      e for e in os.listdir(cwd)
                      if not e.startswith('.')
                  ][:15]
                  lines.append(f"CWD: {cwd}")
                  lines.append(f"FILES: {', '.join(entries) if entries else '(empty)'}")
              except PermissionError:
                  lines.append(f"CWD: {cwd} (cannot list files)")
              except FileNotFoundError:
                  lines.append(f"CWD: {cwd} (directory not found)")
          except Exception:
              pass

          # Inject allowed write roots from guardrails
          try:
              from ...security.guardrails_manager import get_guardrails
              roots = [str(r) for r in get_guardrails().rules.allowed_write_roots]
              if roots:
                  lines.append(f"ALLOWED WRITE ROOTS: {', '.join(roots)}")
                  lines.append("NOTE: You may only create/write/delete files inside ALLOWED WRITE ROOTS.")
          except Exception:
              pass

      elif domain == "app":
          try:
              from ...perception.System.process import get_process_manager
              target = (step.target or "").lower().replace(".exe", "").strip()
              if target:
                  matches = get_process_manager().find_all_processes(target)
                  if matches:
                      proc_list = ", ".join(
                          f"{p.name} (PID {p.pid})" for p in matches[:5]
                      )
                      lines.append(f"RUNNING: {proc_list}")
                  else:
                      lines.append(f"RUNNING: no processes matching '{target}' found")
          except Exception:
              pass

      if not lines:
          return ""
      return "\nENVIRONMENT:\n" + "\n".join(f"  {l}" for l in lines)

def build_step_prompt(step: IntentStep, context: ExecutionContext) -> tuple:
    """
    Assembles the single-step prompt for the planner LLM.

    Returns:
        (prompt: str, tool_names: list[str])
        tool_names is passed to chat_tool_call for constrained decoding.
    """
    try:
        from ...memory.graph.preference import get_preferences_for_prompt
        pref_str = get_preferences_for_prompt()
    except Exception:
        pref_str = ""

    # ── Retrieve relevant tools ──────────────────────────────────────────────
    retrieved_names = _retrieve_tools(step.description, step.domain, top_k=5)

    # ── Build mini-catalog from retrieved tools only ─────────────────────────
    mini_catalog = "\n".join(
        f"  {TOOL_DETAIL[name]}"
        for name in retrieved_names
        if name in TOOL_DETAIL
    )

    # ── Completed steps context ──────────────────────────────────────────────
    completed = context.get_variable("completed_steps", [])
    steps_so_far = ""
    if completed:
        steps_so_far = "\nCOMPLETED STEPS SO FAR:\n" + "\n".join(
            f"  ✓ {s}" for s in completed
        )

    cdp_active = context.get_variable("browser_cdp_active", False)
    env_state = _get_env_state(step, context)

    prompt = f"""USER GOAL: {step.description}
EXPECTED OUTCOME: {step.expected_output}
DOMAIN: {step.domain}
ACTIVE WINDOW: {context.get_variable('current_window_title', 'Desktop')}
CURRENT URL: {context.get_variable('current_url', '')}
BROWSER CDP ACTIVE: {cdp_active}{env_state}
CWD: {context.get_variable('cwd', '')}
PREFERENCES: {pref_str or 'None'}
LAST ERROR (IF RETRY): {context.get_variable('last_step_error', 'None')}{steps_so_far}

AVAILABLE ACTIONS:
{mini_catalog}

CRITICAL RULES:
1. If BROWSER CDP ACTIVE is True, use web_* tools for browser interactions, not type_text/click.
2. For creating files, use create_file_or_folder with a full absolute path. Do NOT open a text editor.

Select the EXACT single tool call to achieve this step only.
Respond with JSON ONLY: {{"action": "...", "parameters": {{...}}}}
"""

    return prompt, retrieved_names
