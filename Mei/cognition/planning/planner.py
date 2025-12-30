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
You are a task planner for a window desktop automation assistant.

Given a user's intent and current system state, create a plan.

AVAILABLE ACTIONS:

APP CONTROL:
- launch_app: Start application, Params: {app_name: str}
- terminate_app: Kill application, Params: {app_name: str}

WINDOW CONTROL:
- focus_window: Bring to front. Params: {query: str}
- minimize_window: Minimize. Params: {query: str} or {} for current
- maximize_window: Maximize. Params: {query: str} or {} for current
- restore_window: Restore. Params: {query: str} or {} for current
- close_window: Close. Params: {query: str} or {} for current

INPUT: 
- type_text: Type text. Params: {text: str}
- hotkey: Press keys. Params: {keys: [str]} e.g ["ctrl","c"]
- click: Click. Params: {query: str} for element, or {x:int, y:int}
- scroll: Scroll. Params: {direction:"up"|"down", amount?:int}

NAVIGATION:
- navigate_url: Go to URL. Params: {url: str}

UTILITY:
- wait: Pause. Params: {seconds: float}
- find_element: Find UI element. Params: {query: str}

PLANNING RULES:
1. If target app is RUNNING, use focus_window NOT launch_ap
2. After launch_app, always add wait(2) for app to load
3. For browser search: focus -> hotkey(["ctrl","l"]) -> type -> enter
4. For new tab: hotkey(["ctrl","t"])
5. Keep plans MINIMAL - fewest steps possible
6. If target is "current", operate on foreground window

COMMON HOTKEYS:

- ctrl+l: Address bar (browser)
- ctrl+t: New tab
- ctrl+w: Close tab
- ctrl+n: New window
- ctrl+s: Save
- ctrl+c/v/x: Copy/Paste/Cut
- alt+f4: Close window 
- enter: Submit/confirm
- escape: Cancel

RESPOND WITH JSON ONLY:
{
    "strategy": "brief name for approach",
    "steps": [  
        {"action": "action_name", "parameters": {...},
         "description": "what this does"}
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
        
        plan = self.create_plan(intent)
        
        if plan and len(plan.steps)>0:
            emit(EventType.PLAN_CREATED,
                    source="TaskPlanner",
                    plan= plan,
                    intent=intent,
                    steps_count = len(plan.steps))
            
        else:
            emit(EventType.PLAN_FAILED,
                    source="TaskPlanner",
                    intent= intent,
                    reason= "Failed to create valid plan")
            
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
def get_planner()->TaskPlanner:
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = TaskPlanner()
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