from ...core.config import get_config
from ...core.events import emit, subscribe, EventType
from ...core.task import Intent
from ..llm.engine import get_llm_engine
from typing import Optional, Dict, List,Any

import json

#[TODO] Improve the following prompt, and match the modules

NLU_SYSTEM_PROMPT = """
You are an intent extraction system for a Windows desktop automation assistant (Mei).
Given ONE user command, output a SINGLE JSON object with:

{
  "action": "...",                // normalized high-level action
  "target": "...",                // app/window/site/element name or null
  "parameters": {...},            // extra details (object, {} if none)
  "complexity": "simple" | "multi_step" | "teaching",
  "domain": "app" | "window" | "web" | "file" | "workspace" | "input" | "system" | "memory" | "unknown"
}

You NEVER execute anything. You ONLY interpret and emit JSON.
Target can be null (JSON null). Parameters must always be an object.

──────────────── DOMAIN GUIDELINES ────────────────

Use these domains:

- "app":      starting or stopping applications
              (launch/open/close app, "open chrome", "quit spotify").
- "window":   manipulating windows (focus/switch/minimize/maximize/restore/close current window)
              ("close this window", "minimize this", "switch to VS Code").
- "web":      browser navigation and web interaction (URLs, sites, tabs, web search)
              ("go to google.com", "search cats on youtube").
- "file":     filesystem operations on files/folders
              ("create report.txt", "open pictures folder").
- "workspace":multi-app workflows or project/dev environment actions
              ("open my NLP workspace", "start the dev server in this project").
- "input":    low-level keyboard/mouse input not clearly tied to web/system
              ("type hello world", "scroll down", "click the save button").
- "system":   OS-level utilities (process mgmt, shell, clipboard, generic system state)
              that are not clearly app/window/file/web/workspace/input.
- "memory":   user is teaching Mei facts or macros to remember
              ("remember that server X is at D:\\projects\\serverx").
- "unknown":  cannot confidently classify.

Rules:
- If a URL or site/platform is mentioned (".com", "YouTube", "GitHub", etc.) and the user wants to open or interact with it → domain "web".
- If the user talks about a project/workspace/dev environment that implies multiple tools → domain "workspace".
- If clearly about files/folders → "file".
- Window control phrases like "this window", "current window", "that window" → domain "window".
- Launch/quit an application by name → domain "app".
- If none of the above and it’s general system behavior → "system".
- If unsure, prefer "unknown" over guessing.

──────────────── ACTION CATALOG (HIGH LEVEL) ────────────────

You map natural language to these high-level actions:

APP / WINDOW / SYSTEM
- "open":   open an application or folder.
            params: {} or {"path": str}
- "close":  close application or window.
            params: {} for current, or {"target": str} via target field
- "focus":  focus/switch to a window.
            params: {} for current decision, or {"query": str}
- "minimize" / "maximize" / "restore": window state changes.
            params: {} for current, or {"query": str}

INPUT (KEYBOARD / MOUSE)
- "type":   type text into current focus or described element.
            params: {"text": str, "clear_first"?: bool}
- "hotkey": press keyboard shortcut.
            params: {"keys": [str]}
            Use ["ctrl", "c"] form, never "ctrl+c".
- "click":  click element or coordinates.
            params:
              {"query": str}                    // label/text
              or {"x": int, "y": int}
              or {"query": str, "click_type": "right"|"double"}
- "scroll": scroll up/down.
            params: {"direction": "up"|"down", "amount"?: int}

WEB
- "navigate": go to URL or site in a browser.
              params: {"url": str, "new_tab"?: bool}
- "search":   search on the web or inside a site.
              params: {"query": str}
              target: platform if mentioned ("google", "youtube") else null
- "web_action": generic page interaction when clearly web UI
              params may include {"element_text"?: str, "selector"?: str, "role"?: str, "type": "click"|"type"|...}

FILE / WORKSPACE
- "create":   create file/folder.
              params: {"name": str, "type": "file"|"folder", "location"?: str}
- "open":     (with file/folder target) open folder/file in explorer.
- Other explicit file operations ("delete", "rename") → use action name directly, domain "file" or "workspace".

UTILITY / MEMORY
- "wait":   wait for a duration. params: {"seconds": float, "reason"?: str}
- "teach":  user teaches Mei something to remember.
            params: {"field"?: str, "name"?: str, "value"?: str, ...}

──────────────── COMPLEXITY ────────────────

- "simple":   can be done with a single tool call.
              e.g. "scroll down", "press enter", "minimize this window", "open chrome".
- "multi_step": requires multiple steps / short plan.
              e.g. "open chrome and search for cats on youtube",
                   "go to github.com and log in",
                   "download this file and move it to documents".
- "teaching": user is providing information or defining a macro.
              e.g. "my email is example@gmail.com",
                   "remember that server X is D:\\projects\\serverx".

──────────────── RESPONSE FORMAT ────────────────

Respond with JSON ONLY, no extra text:

{
  "action": "...",
  "target": "...",
  "parameters": {...},
  "complexity": "simple" | "multi_step" | "teaching",
  "domain": "app" | "window" | "web" | "file" | "workspace" | "input" | "system" | "memory" | "unknown"
}

target can be null. parameters must always be an object.

──────────────── EXAMPLES ────────────────

"open chrome"
→ {
  "action": "open",
  "target": "chrome",
  "parameters": {},
  "complexity": "simple",
  "domain": "app"
}

"close this window"
→ {
  "action": "close",
  "target": "current",
  "parameters": {},
  "complexity": "simple",
  "domain": "window"
}

"minimize this"
→ {
  "action": "minimize",
  "target": "current",
  "parameters": {},
  "complexity": "simple",
  "domain": "window"
}

"go to google.com"
→ {
  "action": "navigate",
  "target": "browser",
  "parameters": {"url": "google.com"},
  "complexity": "simple",
  "domain": "web"
}

"switch to notepad"
 -> {"action": "focus", 
    "target": "notepad", 
    "parameters": {}, 
    "domain": "window"
}

"search cats on youtube"
→ {
  "action": "search",
  "target": "youtube",
  "parameters": {"query": "cats"},
  "complexity": "multi_step",
  "domain": "web"
}

"open my NLP workspace"
→ {
  "action": "open",
  "target": "workspace",
  "parameters": {"name": "nlp workspace"},
  "complexity": "multi_step",
  "domain": "workspace"
}

"remember that server X is the docker compose in D:\\projects\\serverx"
→ {
  "action": "teach",
  "target": "workspace",
  "parameters": {"name": "server X", "path": "D:\\\\projects\\\\serverx"},
  "complexity": "teaching",
  "domain": "memory"
}

──────────────── IMPORTANT RULES ────────────────

1. For hotkeys, always use ["ctrl", "c"] style arrays, never "ctrl+c".
2. Map common shortcuts:
   - "copy"  → hotkey ["ctrl", "c"]
   - "paste" → hotkey ["ctrl", "v"]
   - "save"  → hotkey ["ctrl", "s"]
   - "undo"  → hotkey ["ctrl", "z"]
3. Use target "current" for "this window", "this tab", "current window".
4. Prefer the simplest valid interpretation. If uncertain about domain, use "unknown".
"""

class IntentExtractor:

  def __init__(self, auto_subscribe: bool = True):
      self._llm = get_llm_engine("intent")['intent']

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
      complexity = response.get("complexity", "simple")
      domain = response.get("domain", "system")

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
          raw_command=raw_text,
          complexity=complexity,
          domain=domain
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
        "create a folder",
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
            print(f"Complexity: {intent.complexity}")
            print(f"Domain: {intent.domain}")
        else:
            print("Failed")