from ...core.config import get_config
from ...core.events import emit, subscribe, EventType
from ...core.task import Intent
from ..llm.engine import get_llm_engine
from typing import Optional, Dict, List,Any

import json

NLU_SYSTEM_PROMPT = """
You are an intent extraction system for a Windows desktop assistant.

Given a user command, extract:

- action: The main action (open, close, search, type, click, focus, minimize, scroll, naviagate, etc. )
- target: The application, window or element ( can be null ) 
- parameters: Additional details as key-value pairs

Common Actions:
- open/launch: Start an application
- close      : CLose window/app
- focus/switch: Bring window to front
- minimzie/maximize/restore: Window state
- search:    : Search for something ( usually in browser/app )
- type: Type text
- click: Click on something
- scroll: scroll up/down
- navigate: Go to URL or path

Respond with JSON only: 
{"action":"...","target":"...","parameters":{...}}

Examples:
APP CONTROL:
"open chrome" → {"action": "open", "target": "chrome", "parameters": {}}
"close notepad" → {"action": "close", "target": "notepad", "parameters": {}}
"launch spotify" → {"action": "open", "target": "spotify", "parameters": {}}

WINDOW CONTROL:
"minimize this" → {"action": "minimize", "target": "current", "parameters": {}}
"switch to firefox" → {"action": "focus", "target": "firefox", "parameters": {}}
"maximize the window" → {"action": "maximize", "target": "current", "parameters": {}}

SEARCH/NAVIGATE:
"search cats on youtube" → {"action": "search", "target": "youtube", "parameters": {"query": "cats"}}
"go to google.com" → {"action": "navigate", "target": "browser", "parameters": {"url": "google.com"}}
"find python tutorials" → {"action": "search", "target": null, "parameters": {"query": "python tutorials"}}

FILE OPERATIONS:
"open pictures folder" → {"action": "open", "target": "folder", "parameters": {"path": "pictures"}}
"create new file" → {"action": "create", "target": "file", "parameters": {"name": null}}
"create file report.txt in documents" → {"action": "create", "target": "file", "parameters": {"name": "report.txt", "location": "documents"}}

INPUT:
"type hello world" → {"action": "type", "target": null, "parameters": {"text": "hello world"}}
"press control c" → {"action": "hotkey", "target": null, "parameters": {"keys": ["ctrl", "c"]}}
"scroll down" → {"action": "scroll", "target": null, "parameters": {"direction": "down"}}
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

def get_intent_extractor() ->IntentExtractor:
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = IntentExtractor()
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