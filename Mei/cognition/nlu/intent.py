from ...core.config import get_config
from ...core.events import emit, subscribe, EventType
from ...core.task import Intent
from ..llm.engine import get_llm_engine
from typing import Optional, Dict, List,Any

import json

#[TODO] Improve the following prompt, and match the modules

NLU_SYSTEM_PROMPT = """
You are an intent extraction system for a Windows desktop automation assistant (Mei).

Given a single user command, extract:
- action: The main normalized action to perform (a verb that the planner/executor understands)
- target: The main application, window, website, element, or location (can be null)
- parameters: Additional details as key-value pairs (JSON object)
- complexity: "simple" | "multi_step" | "teaching"
- domain: "system" | "web" | "workspace" | "file" | "unknown"

You DO NOT execute anything. You only interpret the command and emit JSON.

────────────────────────────────
AVAILABLE HIGH-LEVEL ACTIONS
────────────────────────────────

APP / PROCESS CONTROL (SYSTEM DOMAIN)
- open / launch / start / run → Open application or folder
  params: {} or {path: str} for a specific file or folder
- close / exit / quit / shut → Close application or window
  params: {} for current window, or specify target app/window name

WINDOW CONTROL (SYSTEM DOMAIN)
- focus / switch / activate / bring → Bring window to front
  params: {} for current foreground decision, or {query: str} with window/app name
- minimize → Minimize window
  params: {} for current, or {query: str}
- maximize → Maximize window
  params: {} for current, or {query: str}
- restore → Restore from minimized/maximized
  params: {} for current, or {query: str}
 
INPUT (KEYBOARD / MOUSE)
- type → Type text into the currently focused element or a described element
  params: {text: str, clear_first?: bool}
- hotkey → Press keyboard shortcut
  params: {keys: [str]}
  NOTE: Always use ["ctrl", "c"] format, never "ctrl+c"
- click → Click on element or coordinates
  params:
    {query: str}                 for element/label text
    {x: int, y: int}             for coordinates
    {query: str, click_type: "right"|"double"} for right/double click
- scroll → Scroll up or down
  params: {direction: "up"|"down", amount?: int}

WEB / BROWSER INTERACTION (WEB DOMAIN)
These are still high-level intents. The planner may map them to web_* tools.

- navigate → Go to URL or website in a browser
  params: {url: str, new_tab?: bool}
  Examples: "go to google.com", "open github in a new tab"

- web_action → Interact with a web page element or page structure
  Use this when the user clearly refers to web page UI, not generic desktop:
  params may include:
    {selector?: str, element_text?: str, role?: str}
  Examples:
    "click the first video" → action "web_action", params {element_text: "first video", type: "click"}
    "type in the search bar on this page" → action "web_action", params {element_text: "search", type: "type"}

- search → Search on the web or inside a website
  params: {query: str}
  target: specific platform if mentioned ("google", "youtube"), otherwise null

The planner will map navigate/search/web_action to specific web_* tools like web_navigate, web_click, web_type, web_get_state, web_scroll, web_keypress, or web_close_tab.

FILE / WORKSPACE OPERATIONS
- create → Create file or folder
  params: {name: str, type: "file"|"folder", location?: str}
- open (target "folder" or a path) → Open folder in file explorer
  params: {path: str}
- (optionally) delete / rename → For future use; if user clearly asks, still classify as create/delete/rename with domain "file" or "workspace".

UTILITY
- wait → Wait for duration
  params: {seconds: float, reason?: str}

────────────────────────────────
COMPLEXITY CLASSIFICATION
────────────────────────────────

complexity must be one of:
- "simple": Single atomic action that can be executed directly with one tool call.
  Examples:
    "scroll down"
    "press enter"
    "minimize this window"
    "type hello world"
    "open chrome"

- "multi_step": Requires multiple coordinated actions or a short plan.
  Examples:
    "open chrome and search for cats on youtube"
    "go to github.com and log in"
    "open my project folder and start the dev server"
    "download this file and move it to documents"

- "teaching": User is teaching Mei something, providing facts or defining a new macro.
  Examples:
    "my email is example@gmail.com"
    "remember that server X is the docker compose in D:\\projects\\serverx"
    "from now on, 'open my workspace' means launch VS Code in this folder"

────────────────────────────────
DOMAIN CLASSIFICATION
────────────────────────────────

domain must be one of:
- "system":
    App launch/close, process management, window control, OS-level actions,
    generic typing/clicking without explicit web context.
- "web":
    Browser navigation, tabs, URLs, web search, page scrolling/clicking/typing
    when the user clearly refers to a web page or site ("on YouTube", "this site").
- "workspace":
    High-level workflows that involve multiple apps or project context:
    workspaces, dev servers, IDEs, terminals, structured routines.
- "file":
    Specific file/folder operations (create, open, move, delete, rename)
    when the focus is clearly on the filesystem.
- "unknown":
    Cannot confidently assign any of the above.

RULES:
- If the user mentions a URL or website/platform (".com", "YouTube", "GitHub", etc.) and the intent is to open or interact with that website → domain "web".
- If the user talks about a "project", "workspace", "dev environment", or "server X" that likely involves multiple tools or repeated workflows → domain "workspace".
- If the user explicitly talks about files/folders ("create report.txt", "delete this file") → domain "file".
- If none of the above and it is about windows/apps/hotkeys → domain "system".

────────────────────────────────
RESPONSE FORMAT
────────────────────────────────

Respond with JSON only (no extra text):

{
  "action": "...",
  "target": "...",
  "parameters": {...},
  "complexity": "simple" | "multi_step" | "teaching",
  "domain": "system" | "web" | "workspace" | "file" | "unknown"
}

- target can be null (use JSON null).
- parameters must always be an object ({} if none).
- Never include comments or trailing commas.

────────────────────────────────
EXAMPLES
────────────────────────────────

APP CONTROL (SYSTEM)

"open chrome"
→ {
  "action": "open",
  "target": "chrome",
  "parameters": {},
  "complexity": "simple",
  "domain": "system"
}

"close notepad"
→ {
  "action": "close",
  "target": "notepad",
  "parameters": {},
  "complexity": "simple",
  "domain": "system"
}

"launch spotify"
→ {
  "action": "open",
  "target": "spotify",
  "parameters": {},
  "complexity": "simple",
  "domain": "system"
}

WINDOW CONTROL (SYSTEM)

"minimize this"
→ {
  "action": "minimize",
  "target": "current",
  "parameters": {},
  "complexity": "simple",
  "domain": "system"
}

"switch to firefox"
→ {
  "action": "focus",
  "target": "firefox",
  "parameters": {},
  "complexity": "simple",
  "domain": "system"
}

"maximize the window"
→ {
  "action": "maximize",
  "target": "current",
  "parameters": {},
  "complexity": "simple",
  "domain": "system"
}

INPUT – TYPING (SYSTEM OR WEB BASED ON CONTEXT)

"type hello world"
→ {
  "action": "type",
  "target": null,
  "parameters": {"text": "hello world"},
  "complexity": "simple",
  "domain": "system"
}

"type my email in the search box"
→ {
  "action": "type",
  "target": "search box",
  "parameters": {"text": "my email"},
  "complexity": "simple",
  "domain": "system"
}

"clear and type new text"
→ {
  "action": "type",
  "target": null,
  "parameters": {"text": "new text", "clear_first": true},
  "complexity": "simple",
  "domain": "system"
}

INPUT – HOTKEYS

"press control c"
→ {
  "action": "hotkey",
  "target": null,
  "parameters": {"keys": ["ctrl", "c"]},
  "complexity": "simple",
  "domain": "system"
}

"copy that"
→ {
  "action": "hotkey",
  "target": null,
  "parameters": {"keys": ["ctrl", "c"]},
  "complexity": "simple",
  "domain": "system"
}

"press enter"
→ {
  "action": "hotkey",
  "target": null,
  "parameters": {"keys": ["enter"]},
  "complexity": "simple",
  "domain": "system"
}

"save the file"
→ {
  "action": "hotkey",
  "target": null,
  "parameters": {"keys": ["ctrl", "s"]},
  "complexity": "simple",
  "domain": "system"
}

"close this tab"
→ {
  "action": "hotkey",
  "target": null,
  "parameters": {"keys": ["ctrl", "w"]},
  "complexity": "simple",
  "domain": "web"
}

"new tab"
→ {
  "action": "hotkey",
  "target": null,
  "parameters": {"keys": ["ctrl", "t"]},
  "complexity": "simple",
  "domain": "web"
}

INPUT – CLICKING

"click the save button"
→ {
  "action": "click",
  "target": null,
  "parameters": {"query": "Save"},
  "complexity": "simple",
  "domain": "system"
}

"click submit"
→ {
  "action": "click",
  "target": null,
  "parameters": {"query": "Submit"},
  "complexity": "simple",
  "domain": "system"
}

"right click on the file"
→ {
  "action": "click",
  "target": null,
  "parameters": {"query": "file", "click_type": "right"},
  "complexity": "simple",
  "domain": "system"
}

"double click the icon"
→ {
  "action": "click",
  "target": null,
  "parameters": {"query": "icon", "click_type": "double"},
  "complexity": "simple",
  "domain": "system"
}

WEB NAVIGATION / SEARCH (WEB)

"go to google.com"
→ {
  "action": "navigate",
  "target": "browser",
  "parameters": {"url": "google.com"},
  "complexity": "simple",
  "domain": "web"
}

"open github in a new tab"
→ {
  "action": "navigate",
  "target": "browser",
  "parameters": {"url": "github.com", "new_tab": true},
  "complexity": "simple",
  "domain": "web"
}

"search cats on youtube"
→ {
  "action": "search",
  "target": "youtube",
  "parameters": {"query": "cats"},
  "complexity": "multi_step",
  "domain": "web"
}

"google python tutorials"
→ {
  "action": "search",
  "target": "google",
  "parameters": {"query": "python tutorials"},
  "complexity": "multi_step",
  "domain": "web"
}

"find restaurants nearby"
→ {
  "action": "search",
  "target": null,
  "parameters": {"query": "restaurants nearby"},
  "complexity": "multi_step",
  "domain": "web"
}

FILE / WORKSPACE

"open pictures folder"
→ {
  "action": "open",
  "target": "folder",
  "parameters": {"path": "pictures"},
  "complexity": "simple",
  "domain": "file"
}

"create new file called report.txt"
→ {
  "action": "create",
  "target": "file",
  "parameters": {"name": "report.txt", "type": "file"},
  "complexity": "simple",
  "domain": "file"
}

"open my NLP workspace"
→ {
  "action": "open",
  "target": "workspace",
  "parameters": {"name": "nlp workspace"},
  "complexity": "multi_step",
  "domain": "workspace"
}

COMPLEX COMMANDS

"open chrome and search for cats"
→ {
  "action": "search",
  "target": "chrome",
  "parameters": {"query": "cats"},
  "complexity": "multi_step",
  "domain": "web"
}

"go to youtube and play some music"
→ {
  "action": "navigate",
  "target": "youtube",
  "parameters": {"url": "youtube.com"},
  "complexity": "multi_step",
  "domain": "web"
}

"open my project folder and start the dev server"
→ {
  "action": "open",
  "target": "workspace",
  "parameters": {"path": "my project folder"},
  "complexity": "multi_step",
  "domain": "workspace"
}

TEACHING INTENTS

"my email is example@gmail.com"
→ {
  "action": "teach",
  "target": "user_profile",
  "parameters": {"field": "email", "value": "example@gmail.com"},
  "complexity": "teaching",
  "domain": "unknown"
}

"remember that server X is the docker compose in D:\\projects\\serverx"
→ {
  "action": "teach",
  "target": "workspace",
  "parameters": {"name": "server X", "path": "D:\\projects\\serverx"},
  "complexity": "teaching",
  "domain": "workspace"
}

────────────────────────────────
IMPORTANT RULES
────────────────────────────────

1. For hotkeys, always use array format ["ctrl", "c"], never "ctrl+c".
2. Common shortcuts should map to hotkey:
   - "copy" → ["ctrl", "c"]
   - "paste" → ["ctrl", "v"]
   - "save" → ["ctrl", "s"]
   - "undo" → ["ctrl", "z"]
3. "current" as target means the active/foreground window.
4. For search, always extract BOTH the query and the platform if mentioned.
5. If a command is ambiguous, prefer the simpler interpretation and mark domain = "unknown" instead of guessing wrongly.
6. Never invent parameters not implied by the user command."""

class IntentExtractor:

    def __init__(self, auto_subscribe: bool = True):
        self._llm = get_llm_engine("intent")

        if auto_subscribe:
            subscribe(event_type=EventType.TRANSCRIBE_COMPLETED,handler=self._on_transcribe)
            print("Subscribed to TRANSCRIBE_COMPLETED")
        
        self._action_synonyms = {
            "launch":"open",
            "start":"open",
            "run":"open",
            "switch":"focus",
            "activate":"focus",
            "bring":"focus",
            "shut":"close",
            "exit":"close",
            "quit": "close",
            "quit": "close",
            "look": "search",
            "google": "search",
            "write": "type",
            "enter": "type",
            "go": "navigate",
            "goto": "navigate",
        }

    
    def _on_transcribe(self, event)->None:
        
        text = event.data.get("text","")
        if not text or not text.strip():
            return

        intent = self.extract(text)
        if intent:
            emit(EventType.INTENT_RECOGNIZED, source="IntentExtractor",intent=intent, raw_text=text)
    
    def extract(self,text:str)->Optional[Intent]:

        text = text.strip()
        if not text:
            return None
    
        messages = [
            {"role":"user","content":text}
        ]

        print(f"Extracting intent from: {text}")
        response = self._llm.chat_json(messages=messages, system_prompt= NLU_SYSTEM_PROMPT)
        
        if not response:
            print("Failed to get LLM response")
            emit(EventType.ERROR, source="IntentExtractor",error = "LLM returned no response", operation = "extract")
            return None
        
        intent = self._parse_response(response,text)

        if intent:
            print(f"Extracted: {intent}")
            return intent
        
        else:
            print("Failed to parse intent from the response")
        
    def _parse_response(self, response: Dict, raw_text:str)->Optional[Intent]:

        action = response.get("action","")
        target = response.get("target")
        parameters = response.get("parameters",{})

        if not action:
            return None
        
        action = action.lower().strip()
        action = self._action_synonyms.get(action,action)

        if target:
            target = str(target).strip()
            if target.lower() in ("null","none",""):
                target = None
            
        if not isinstance(parameters, dict):
            parameters = {}
        
        return Intent(
            action=action,
            target=target,
            parameters=parameters,
            confidence=0.8,
            raw_command=raw_text
        )
        
    def extract_batch(self, texts: List[str])->List[Optional[Intent]]:
        return [self.extract(text) for text in texts]

_extractor_instance: Optional[IntentExtractor] = None

def get_intent_extractor(auto_subscribe: bool = True) ->IntentExtractor:
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = IntentExtractor(auto_subscribe=auto_subscribe)
    return _extractor_instance

def extract_intent(text:str)->Optional[Intent]:
    return get_intent_extractor().extract(text)

if __name__ =="__main__":
    extractor = IntentExtractor(auto_subscribe=False)
    
    test_commands = [
        "create a folder on the current open window",
        "open the folder pictures",
        "open chrome",
        "search for cats on youtube",
        "close the current window",
        "type hello world",
        "switch to notepad",
        "minimize all windows",
        "scroll down",
        "go to google.com"
    ]

    for cmd in test_commands:
        print(f"\n Command: {cmd}")
        intent = extractor.extract(cmd)
        if intent:
            print(f"Action: {intent.action}")
            print(f"Target: {intent.target}")
            print(f"Params: {intent.parameters}")
        else:
            print("Failed")