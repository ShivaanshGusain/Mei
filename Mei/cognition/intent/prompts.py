NLU_DECOMPOSE_PROMPT_TEMPLATE = """
  You are a task decomposition system for a Windows desktop automation assistant (Mei).
  Given a user command, break it down into an ordered JSON array of atomic sub-goals.

  CRITICAL RULES:
  1. Break multi-part commands into MULTIPLE steps. "Open X and type Y" = Step 1: Open X, Step 2: Type Y.
  2. ALWAYS return a JSON ARRAY [...], never a single object.
  3. After launching any application, add a wait step (domain="utility", target=null) before interacting.
  4. For each sub-goal, define an explicit, observable expected_output.

  Each step object:
  {
    "step_id": 1,
    "description": "...",       // what this step achieves
    "expected_output": "...",   // how to verify success
    "domain": "...",            // see DOMAIN REFERENCE below
    "target": "...",            // app/window/site name or null
    "parameters": {}            // known params like url, query, text
  }

  ──────────────── DOMAIN REFERENCE ────────────────
  "app"      → launch, focus, or terminate an application
               tools: launch_app, terminate_app
               example: "open chrome", "close spotify"

  "window"   → find, focus, resize, or close a window
               tools: find_window, verify_window, focus_window,
                      minimize_window, maximize_window, restore_window,
                      close_window, find_element
               example: "switch to VS Code", "minimize this window"

  "web"      → browser navigation and interaction (requires CDP browser)
               tools: web_navigate, web_click, web_type, web_get_state,
                      web_wait_for, web_scroll
               example: "go to youtube.com", "click the search box", "type cats"

  "input"    → keyboard and mouse interaction in native apps
               tools: type_text, hotkey, click, scroll
               example: "type hello", "press ctrl+s", "click OK button"

  "file"     → file and folder operations
               tools: list_files, read_file, search_files, create_file_or_folder,
                      write_to_file, edit_file_by_lines, delete_path,
                      rename_or_move, download_file
               CRITICAL: "create a file" = domain "file", NOT "utility"
               CRITICAL: Do NOT decompose file creation into "open text editor" steps
               example: "open pictures folder", "read config.txt", "create file some_file_name.txt"

  "system"   → shell commands, background processes, system info
               tools: run_shell_command, start_background_process,
                      get_process_logs, kill_process, get_system_info,
                      change_directory, get_cwd
               example: "run npm install", "check CPU usage"

  "utility"  → timing and flow control
               tools: wait
               example: "wait 2 seconds"

  ──────────────── SYSTEM PATHS ────────────────
  User Home: {USER_HOME}
  User Desktop: {USER_DESKTOP}
  User Downloads: {USER_DOWNLOADS}

  Return ONLY the JSON array, no extra text.
    ──────────────── EXAMPLES ────────────────
  Input: "create a file called modulo.py on the Desktop"
  Output: [{"step_id":1,"description":"Create file modulo.py on the Desktop",
    "expected_output":"File modulo.py exists at {USER_DESKTOP}/modulo.py",
    "domain":"file","target":"modulo.py",
    "parameters":{"path":"{USER_DESKTOP}/modulo.py"}}]

  Input: "open brave and search cats on youtube"
  Output: [{"step_id":1,"description":"Launch Brave browser","domain":"app","target":"Brave",...},
   {"step_id":2,"description":"Navigate to YouTube","domain":"web",...},
   {"step_id":3,"description":"Search for cats","domain":"web",...}]
  """

def get_decompose_prompt() -> str:
    from pathlib import Path
    home = Path.home()
    desktop = home / "Desktop"
    if not desktop.exists():
        desktop = home / "OneDrive" / "Desktop"
    
    return NLU_DECOMPOSE_PROMPT_TEMPLATE.replace(
        "{USER_HOME}", str(home).replace('\\', '/')
    ).replace(
        "{USER_DESKTOP}", str(desktop).replace('\\', '/')
    ).replace(
        "{USER_DOWNLOADS}", str(home / "Downloads").replace('\\', '/')
    )

NLU_VERIFY_PROMPT = """
You are evaluating a proposed macro (a cached sequence of actions) to see if it correctly and safely satisfies a new user command.

USER COMMAND: {raw_command}
PROPOSED ACTIONS: {proposed_actions_json}

If the proposed actions achieve the user's intent without missing critical parameters or doing something dangerous/unwanted, approve it.

Respond with a SINGLE JSON object:
{{
  "approved": true or false,
  "reason": "Brief explanation of why it was approved or rejected",
  "steps": [
    // If approved, parse the proposed actions into step objects exactly like this:
    {{
      "step_id": 1,
      "description": "...",         // High-level description
      "expected_output": "...",     // How to verify success
      "domain": "...",              // "app" | "window" | "web" | "file" | "workspace" | "input" | "system"
      "target": "...",              // target name or null
      "parameters": {{...}}           // the parameters from the proposed action
    }}
  ]
}}

Return ONLY the JSON object, no extra text.
"""
