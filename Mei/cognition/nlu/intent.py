from ...core.config import get_config
from ...core.events import emit, subscribe, EventType
from ...core.task import Intent
from ..llm.engine import get_llm_engine
from typing import Optional, Dict, List,Any

import json

NLU_SYSTEM_PROMPT = """
You are an intent extraction system for a Windows desktop automation assistant.

Given a user command, extract:
- action: The main action to perform
- target: The application, window, element, or location (can be null)
- parameters: Additional details as key-value pairs

APP CONTROL:
  open/launch    → Open application
                   params: {} or {path: str} for specific file
  
  close/exit     → Close application or window
                   params: {} for current, or specify target

WINDOW CONTROL:
  focus/switch   → Bring window to front
                   params: {}
  
  minimize       → Minimize window
                   params: {}
  
  maximize       → Maximize window
                   params: {}
  
  restore        → Restore minimized/maximized window
                   params: {}

INPUT:
  type           → Type text
                   params: {text: str, clear_first?: bool}
  
  hotkey         → Press keyboard shortcut
                   params: {keys: [str]}
                   Note: Use ["ctrl", "c"] format, not "ctrl+c"
  
  click          → Click on element or coordinates
                   params: {query: str} for element name
                   params: {x: int, y: int} for coordinates
                   params: {query: str, click_type: "right"} for right-click
  
  scroll         → Scroll up or down
                   params: {direction: "up"|"down", amount?: int}

NAVIGATION:
  navigate       → Go to URL or file path
                   params: {url: str, new_tab?: bool}
  
  search         → Search for something (usually in browser)
                   params: {query: str}

FILE OPERATIONS:
  create         → Create file or folder
                   params: {name: str, type: "file"|"folder", location?: str}

UTILITY:
  wait           → Wait for duration
                   params: {seconds: float, reason?: str}

                   
RESPONSE FORMAT

Respond with JSON only:
{"action": "...", "target": "...", "parameters": {...}}


EXAMPLES

APP CONTROL:
  "open chrome"
  → {"action": "open", "target": "chrome", "parameters": {}}
  
  "close notepad"
  → {"action": "close", "target": "notepad", "parameters": {}}
  
  "launch spotify"
  → {"action": "open", "target": "spotify", "parameters": {}}

WINDOW CONTROL:
  "minimize this"
  → {"action": "minimize", "target": "current", "parameters": {}}
  
  "switch to firefox"
  → {"action": "focus", "target": "firefox", "parameters": {}}
  
  "maximize the window"
  → {"action": "maximize", "target": "current", "parameters": {}}

INPUT - TYPING:
  "type hello world"
  → {"action": "type", "target": null, "parameters": {"text": "hello world"}}
  
  "type my email in the search box"
  → {"action": "type", "target": "search box", "parameters": {"text": "my email"}}
  
  "clear and type new text"
  → {"action": "type", "target": null, "parameters": {"text": "new text", "clear_first": true}}

INPUT - HOTKEYS:
  "press control c"
  → {"action": "hotkey", "target": null, "parameters": {"keys": ["ctrl", "c"]}}
  
  "copy that"
  → {"action": "hotkey", "target": null, "parameters": {"keys": ["ctrl", "c"]}}
  
  "press enter"
  → {"action": "hotkey", "target": null, "parameters": {"keys": ["enter"]}}
  
  "save the file"
  → {"action": "hotkey", "target": null, "parameters": {"keys": ["ctrl", "s"]}}
  
  "close this tab"
  → {"action": "hotkey", "target": null, "parameters": {"keys": ["ctrl", "w"]}}
  
  "new tab"
  → {"action": "hotkey", "target": null, "parameters": {"keys": ["ctrl", "t"]}}

INPUT - CLICKING:
  "click the save button"
  → {"action": "click", "target": null, "parameters": {"query": "Save"}}
  
  "click submit"
  → {"action": "click", "target": null, "parameters": {"query": "Submit"}}
  
  "right click on the file"
  → {"action": "click", "target": null, "parameters": {"query": "file", "click_type": "right"}}
  
  "double click the icon"
  → {"action": "click", "target": null, "parameters": {"query": "icon", "click_type": "double"}}

INPUT - SCROLLING:
  "scroll down"
  → {"action": "scroll", "target": null, "parameters": {"direction": "down"}}
  
  "scroll up a lot"
  → {"action": "scroll", "target": null, "parameters": {"direction": "up", "amount": 10}}

NAVIGATION:
  "go to google.com"
  → {"action": "navigate", "target": "browser", "parameters": {"url": "google.com"}}
  
  "open github in a new tab"
  → {"action": "navigate", "target": "browser", "parameters": {"url": "github.com", "new_tab": true}}

SEARCH:
  "search cats on youtube"
  → {"action": "search", "target": "youtube", "parameters": {"query": "cats"}}
  
  "google python tutorials"
  → {"action": "search", "target": "google", "parameters": {"query": "python tutorials"}}
  
  "find restaurants nearby"
  → {"action": "search", "target": null, "parameters": {"query": "restaurants nearby"}}

FILE OPERATIONS:
  "open pictures folder"
  → {"action": "open", "target": "folder", "parameters": {"path": "pictures"}}
  
  "create new file called report.txt"
  → {"action": "create", "target": "file", "parameters": {"name": "report.txt", "type": "file"}}

COMPLEX COMMANDS (extract primary action):
  "open chrome and search for cats"
  → {"action": "search", "target": "chrome", "parameters": {"query": "cats"}}
  
  "go to youtube and play some music"
  → {"action": "navigate", "target": "youtube", "parameters": {"url": "youtube.com"}}

  
IMPORTANT RULES

1. For hotkeys, always use array format: ["ctrl", "c"] not "ctrl+c"
2. Common shortcuts should map to hotkey action:
   - "copy" → hotkey with ["ctrl", "c"]
   - "paste" → hotkey with ["ctrl", "v"]
   - "save" → hotkey with ["ctrl", "s"]
   - "undo" → hotkey with ["ctrl", "z"]
3. "current" as target means the active/foreground window
4. For search, extract the query and target platform
5. If command is ambiguous, prefer the simpler interpretation
"""

class IntentExtractor:

    def __init__(self, auto_subscribe: bool = True):
        self._llm = get_llm_engine()

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