from ...core.config import get_config
from ...core.events import emit, subscribe, EventType
from ...core.task import Intent, Plan, Step, StepStatus
from ..llm.engine import get_llm_engine
from ...perception.System.windows import WindowManager
from ...perception.System.process import ProcessManager
from typing import Optional, List,Dict, Any
from datetime import datetime
import time

VALID_ACTIONS = {
    "launch_app",     
    "terminate_app",  
    "focus_window",   
    "minimize_window",
    "maximize_window",
    "restore_window", 
    "close_window",   
    "type_text",      
    "hotkey",         
    "click",          
    "scroll",         
    "navigate_url",   
    "wait",           
    "find_element"    
}

PLANNER_SYSTEM_PROMPT = """
You are a task planner for a Windows desktop automation assistant.

Given a user's intent and current system state, create an executable plan.

AVAILABLE ACTIONS & PARAMETERS

APP CONTROL:
 launch_app       
                  Start an application                                  
                  params: {app_name: str}                                   
                  Example: {"app_name": "chrome"}   

                  
 terminate_app    
                  Kill an application                                       
                  params: {app_name: str} OR {pid: int}                     
                  Example: {"app_name": "notepad"}                          

WINDOW CONTROL:
 focus_window     Bring window to front                                     
                  params: {query: str} (window title search)                
                  Example: {"query": "chrome"}                              
 minimize_window  Minimize window                                           
                  params: {query: str} OR {} for current window             
                  Example: {} or {"query": "notepad"}                       
 maximize_window  Maximize window                                           
                  params: {query: str} OR {} for current window             
 restore_window   Restore from minimized/maximized                          
                  params: {query: str} OR {} for current window             
 close_window     Close window                                              
                  params: {query: str} OR {} for current window             

INPUT:
 type_text        Type text into current focus or specific element          
                  params: {                                                 
                    text: str,              (REQUIRED)                      
                    element_query?: str,    (find element first)            
                    clear_first?: bool      (default: false)                
                  }                                                         
                  Example: {"text": "hello world"}                          
                  Example: {"text": "query", "element_query": "search box"} 
 hotkey           Press keyboard shortcut                                   
                  params: {keys: [str]}                                     
                  Example: {"keys": ["ctrl", "c"]}                          
                  Example: {"keys": ["enter"]}                              
                  Example: {"keys": ["alt", "f4"]}                          
 click            Click on element or coordinates                           
                  params: {query: str} for element name/label               
                  params: {x: int, y: int} for coordinates                  
                  params: {query: str, click_type: "right"|"double"}        
                  Example: {"query": "Submit"}                              
                  Example: {"x": 100, "y": 200}                             
 scroll           Scroll mouse wheel                                        
                  params: {direction: "up"|"down", amount?: int}            
                  Example: {"direction": "down"}                            
                  Example: {"direction": "up", "amount": 5}                 

NAVIGATION:
 navigate_url     Go to URL (uses existing browser or opens default)        
                  params: {url: str, new_tab?: bool}                        
                  Example: {"url": "google.com"}                            
                  Example: {"url": "github.com", "new_tab": true}           

UTILITY:
 wait             Pause execution                                           
                  params: {seconds: float, reason?: str}                    
                  Example: {"seconds": 2, "reason": "wait for page load"}   
 find_element     Find and cache UI element (no action)                     
                  params: {query: str, element_type?: str, timeout?: float} 
                  Example: {"query": "Submit button"}                       
                  Example: {"query": "search", "element_type": "edit"}      

                  
PLANNING RULES

1. CHECK IF APP IS RUNNING FIRST
   - If target app IS RUNNING → use focus_window, NOT launch_app
   - If target app is NOT running → use launch_app

2. AFTER LAUNCH, ALWAYS WAIT
   - After launch_app → add wait with 2-3 seconds for app to load
   - Example: launch_app → wait(2) → next action

3. BROWSER SEARCH PATTERN
   For searching in browser:
   a. focus_window (if browser running) OR launch_app + wait
   b. hotkey(["ctrl", "l"]) - focus address bar
   c. type_text with the search query
   d. hotkey(["enter"]) - submit

4. NEW TAB PATTERN
   For opening new tab:
   a. focus_window on browser
   b. hotkey(["ctrl", "t"])
   c. Then navigate or type

5. MINIMAL STEPS
   - Keep plans as SHORT as possible
   - Don't add unnecessary waits
   - Don't add steps that aren't needed

6. CURRENT WINDOW
   - If target is "current", operate on foreground window
   - Use empty params {} for current window operations

7. USE CONTEXT
   - Look at what windows are open
   - Look at what's in foreground
   - Make intelligent decisions based on state

   
COMMON HOTKEYS REFERENCE

Browser:
  ["ctrl", "l"]     → Focus address bar
  ["ctrl", "t"]     → New tab
  ["ctrl", "w"]     → Close tab
  ["ctrl", "tab"]   → Next tab
  ["f5"]            → Refresh

General:
  ["ctrl", "c"]     → Copy
  ["ctrl", "v"]     → Paste
  ["ctrl", "x"]     → Cut
  ["ctrl", "a"]     → Select all
  ["ctrl", "s"]     → Save
  ["ctrl", "z"]     → Undo
  ["ctrl", "n"]     → New window/document
  ["alt", "f4"]     → Close window
  ["enter"]         → Submit/confirm
  ["escape"]        → Cancel
  ["tab"]           → Next field

  
RESPONSE FORMAT


Respond with JSON only:
{
    "strategy": "brief name for your approach",
    "reasoning": "why you chose this approach",
    "steps": [
        {
            "action": "action_name",
            "parameters": {...},
            "description": "human-readable description"
        }
    ]
}


EXAMPLES

EXAMPLE 1: "open notepad" (notepad not running)

Context: {notepad_running: false}

Response:
{
    "strategy": "launch_notepad",
    "reasoning": "Notepad is not running, need to launch it",
    "steps": [
        {
            "action": "launch_app",
            "parameters": {"app_name": "notepad"},
            "description": "Launch Notepad application"
        },
        {
            "action": "wait",
            "parameters": {"seconds": 1.5, "reason": "Wait for Notepad to open"},
            "description": "Wait for application to load"
        }
    ]
}

EXAMPLE 2: "search for cats on youtube" (chrome running)

Context: {chrome_running: true, chrome_window: "YouTube - Google Chrome"}

Response:
{
    "strategy": "search_in_existing_browser",
    "reasoning": "Chrome is already running with YouTube, use address bar to search",
    "steps": [
        {
            "action": "focus_window",
            "parameters": {"query": "chrome"},
            "description": "Focus Chrome window"
        },
        {
            "action": "hotkey",
            "parameters": {"keys": ["ctrl", "l"]},
            "description": "Focus address bar"
        },
        {
            "action": "type_text",
            "parameters": {"text": "youtube.com/results?search_query=cats"},
            "description": "Type YouTube search URL"
        },
        {
            "action": "hotkey",
            "parameters": {"keys": ["enter"]},
            "description": "Navigate to search results"
        }
    ]
}

EXAMPLE 3: "minimize this window"

Context: {foreground: "Visual Studio Code"}

Response:
{
    "strategy": "minimize_current",
    "reasoning": "User wants to minimize the current foreground window",
    "steps": [
        {
            "action": "minimize_window",
            "parameters": {},
            "description": "Minimize current window"
        }
    ]
}

EXAMPLE 4: "type hello world"

Context: {foreground: "Notepad"}

Response:
{
    "strategy": "type_directly",
    "reasoning": "Notepad is in foreground, type directly",
    "steps": [
        {
            "action": "type_text",
            "parameters": {"text": "hello world"},
            "description": "Type 'hello world' into current window"
        }
    ]
}

EXAMPLE 5: "go to github.com in a new tab" (firefox running)

Context: {firefox_running: true}

Response:
{
    "strategy": "new_tab_navigation",
    "reasoning": "Firefox running, open new tab and navigate",
    "steps": [
        {
            "action": "focus_window",
            "parameters": {"query": "firefox"},
            "description": "Focus Firefox window"
        },
        {
            "action": "hotkey",
            "parameters": {"keys": ["ctrl", "t"]},
            "description": "Open new tab"
        },
        {
            "action": "navigate_url",
            "parameters": {"url": "github.com"},
            "description": "Navigate to GitHub"
        }
    ]
}

EXAMPLE 6: "close chrome"

Context: {chrome_running: true}

Response:
{
    "strategy": "close_app",
    "reasoning": "Close Chrome window",
    "steps": [
        {
            "action": "close_window",
            "parameters": {"query": "chrome"},
            "description": "Close Chrome window"
        }
    ]
}
"""

class TaskPlanner:
    def __init__(self, auto_subscribe:bool = True):
        self._llm = get_llm_engine()
        self._window_manager = WindowManager()
        self._process_manager = ProcessManager()

        if auto_subscribe:
            subscribe(event_type=EventType.INTENT_RECOGNIZED, handler=self._on_intent)
            print("Subscribed to INTENT_RECOGNIZED")

    def _on_intent(self, event)-> None:
        intent = event.data.get("intent")
        if not intent:
            print("No intent in event")
            return
        
        cached_plan = self._try_cached_plan(intent)

        if cached_plan:
            print(f"Using cached plan for: {intent.action} -> {intent.target}")
            
            emit(
                EventType.PLAN_CREATED,
                source="TaskPlanner",
                plan=cached_plan,
                intent=intent,
                steps_count=len(cached_plan.steps),
                from_cache=True
            )
            return
    

        plan = self.create_plan(intent)
        
        if plan and len(plan.steps)>0:
            emit(EventType.PLAN_CREATED,
                    source="TaskPlanner",
                    plan= plan,
                    intent=intent,
                    steps_count = len(plan.steps),
                    from_cache = False)
            
        else:
            emit(EventType.PLAN_FAILED,
                    source="TaskPlanner",
                    intent= intent,
                    reason= "Failed to create valid plan")
            
    def _build_intent_pattern(self, intent:Intent)->str:
        pattern = intent.action.lower()

        if intent.target:
            pattern += f":{intent.target.lower()}"

        else:
            pattern +=":"

        variable_actions = ['search', 'type','type_text','navigate','navigate_url']

        if intent.action.lower() in variable_actions:
            pattern += "*"

        return pattern
    
    def _try_cached_plan(self, intent:Intent)->Optional[Plan]:
        
        from ...memory.store import get_memory_store
        import json

        pattern = self._build_intent_pattern(intent)
        print(f"Checking plan cache for pattern: {pattern}")

        try:
            store = get_memory_store()
            cached = store.get_cached_plan(
                intent_pattern= pattern,
                min_success_rate=0.7,
                min_uses= 2
            )

            if not cached:
                print("No cached plan found")
                return None
            
            steps_data = cached.get('plan_steps_json')

            if isinstance(steps_data, str):
                steps_data = json.load(steps_data)

            if not steps_data or not isinstance(steps_data,list):
                print("Cached plan has no valid steps")
                return None
            
            steps = []

            timestamp = int(time.time()*1000)

            for i,step_data in enumerate(steps_data):
                if not isinstance(step_data, dict):
                    continue

                action = step_data.get('action', "")
                if not action or action not in VALID_ACTIONS:
                    print("Cached plan has invalid action: {action}")

                step = Step(
                    id=f"cached_{i}_{timestamp}",
                    action=action,
                    parameters=step_data.get("parameters", {}),
                    description=step_data.get("description", ""),
                    status=StepStatus.PENDING
                )    

                steps.append(step)

            if not steps:
                return None
            
            plan = Plan(
                steps=steps,
                strategy=cached.get("plan_strategy", "cached"),
                reasoning=f"Cached plan (used {cached.get('use_count', 0)} times, "
                          f"success rate: {cached.get('success_count', 0)}/{cached.get('use_count', 0)})",
                created_at=datetime.now()
            )

            print(f"Found cached plan with {len(steps)} steps")
            return plan
        
        except Exception as e:
            print(f"Error checking plan cache: {e}")
            return None
        
    def create_plan(self, intent: Intent)->Optional[Plan]:
        print(f"Creating plan for: {intent.action}->{intent.target}")
        
        start_time = time.time()
        
        context = self._gather_context(intent)

        user_message = self._build_prompt(intent,context)

        messages = [{"role":"user","content":user_message}]
        response = self._llm.chat_json(messages=messages,  system_prompt= PLANNER_SYSTEM_PROMPT)

        if not response:
            print("LLM returned no response")
            emit(EventType.ERROR, source = "TaskPlanner", error = "LLM planning failed")
            return None
        
        plan = self._parse_response(response)

        elapsed =(time.time()-start_time)*1000
        if plan:
            print(f"Plan created in {elapsed:.0f}ms:")
            print(f"Strategy: {plan.strategy}")
            for i, step in enumerate(plan.steps):
                print(f" {i+1}.{step.action}: {step.description}")
        
        else:
            print("Failed to parse plan")
        
        return plan
    
    def _gather_context(self, intent:Intent)->Dict[str,Any]:

        context = {}
        try:
            fg = self._window_manager.get_foreground_window()
            if fg:
                context["foreground"] = {
                    "title": fg.title[:50],
                    "process": fg.process_name
                }
        except Exception as e:
            print(f"Error getting foreground: {e}")

        if intent.target:
            target = intent.target.lower()

            try:
                is_running = self._process_manager.is_running(target)
                context["target_running"] = is_running
            except:
                context["target_running"] = False
            
            try:
                window = self._window_manager.find_window(target)
                context["target_window_found"] = window is not None
                if window:
                    context["target_window_title"] = window.title[:50]
            except:
                context["target_window_found"] = False

            try:
                windows = self._window_manager.get_all_windows()[:5]
                context["open_windows"] = [w.title[:30] for w in windows]
            except:
                context["open_windows"] = []
        return context
    
    def _build_prompt(self, intent:Intent, context:Dict)->str:
        intent_str = f"""
USER INTENT:
Action: {intent.action}
Target: {intent.target}
Parameters: {intent.parameters}
Original command: "{intent.raw_command}"
"""
        context_lines = ["CURRENT SYSTEM STATE:"]

        if "foreground" in context:
            fg = context["foreground"]
            context_lines.append(f"- Active window: \"{fg['title']}\" "f"({fg['process']})")

        if "target_running" in context:
            status = "RUNNING" if context['target_running'] else 'NOT RUNNING'
            context_lines.append(f"- Target app status: {status}")

        if "target_window_found" in context:
            if context["target_window_found"]:
                title = context.get("target_window_title", "unknown")
                context_lines.append(f"- Target window found: \"{title}\"")
            else:
                context_lines.append("- Target window: NOT FOUND")
            
        if "open_windows" in context and context["open_windows"]:
            context_lines.append(f"- Open windows: "
                                    f"{', '.join(context['open_windows'])}")
            
        context_str = "\n".join(context_lines)

        return f"{intent_str}\n{context_str}\n\nCreate a step-by-step plan."
    
    def _parse_response(self, response: Dict)->Optional[Plan]:
        if not isinstance(response, dict):
            return None
        
        steps_data = response.get("steps", [])
        if not steps_data or not isinstance(steps_data,list):
            return None
        
        steps = []
        timestamp = int(time.time()*1000)

        for i, step_data in enumerate(steps_data):
            if not isinstance(step_data, dict):
                continue

            action = step_data.get("action", "")
            if not action or action not in VALID_ACTIONS:
                print(f"Invalid action: {action}")
                continue

            parameters = step_data.get("parameters", {})
            if not isinstance(parameters, dict):
                parameters = {}
            
            description = step_data.get("desctiption", "")

            step = Step(
                id=f"step_{i}_{timestamp}",
                action=action,
                parameters=parameters,
                description=description,
                status=StepStatus.PENDING
            )
            steps.append(step)
    
        if not steps:
            return None
        
        plan = Plan(
            steps= steps,
            strategy=response.get("strategy","generated"),
            reasoning=response.get("reasoning", ""),
            created_at=datetime.now()
        )

        return plan
    
    def plan_direct(self, action: str, target: str = None, parameters: Dict = None)-> Optional[Plan]:
        intent = Intent(
            action = action,
            target= target,
            parameters=parameters,
            raw_command=f"{action} {target}"
        )
        return self.create_plan(intent=intent)
    

_planner_instance: Optional[TaskPlanner] = None
def get_planner(auto_subscribe: bool = True)->TaskPlanner:
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = TaskPlanner(auto_subscribe=auto_subscribe)
    return _planner_instance


if __name__ == "__main__":
    from ..nlu.intent import extract_intent

    planner = TaskPlanner(auto_subscribe=False)
    time.sleep(5)
    test_commands = [
        "open brave",
        "search for cats on youtube",
        "type hello world",
        "switch to notepad"
    ]

    for cmd in test_commands:
        print(f"Command: {cmd}")

        intent = extract_intent(cmd)
        if not intent:
            print("Intent extraction failed")
            continue

        print(f"Intent: {intent.action} -> {intent.target}")
        print(f"Params: {intent.parameters}")

        plan =  planner.create_plan(intent=intent)
        if plan:
            print(f"Strategy: {plan.strategy}")
            print(f"Steps: ({len(plan.steps)})")
            for i, step in enumerate(plan.steps):
                print(f" {i+1}.{step.action}({step.parameters})")
                print(f" {step.description}")
        else:
            print(" Planning failed")