import time
from typing import Dict, Any, Tuple, Optional, List
from datetime import datetime

from ...core.task import ActionHandler
from ...core.config import ActionResult, VerifyResult, ElementReference

from ...perception.System.windows import get_window_manager
from ...perception.System.accessibility import UIAutomationManager
from ...perception.Visual.screen import ScreenCapture
from ...perception.Visual.analyzer import get_visual_analyzer

import pyautogui

from ..context import ExecutionContext


pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

DEFULT_TYPE_INTERVAL = 0.02
DEFAULT_CLICK_PAUSE = 0.1
DEFAULT_SCROLL_AMOUNT = 3

_ui_automation_manager: Optional[UIAutomationManager] = None
_screen_capture: Optional[ScreenCapture] = None

def _get_ui_automation() -> UIAutomationManager:
    global _ui_automation_manager
    if _ui_automation_manager is None:
        _ui_automation_manager = UIAutomationManager()
    return _ui_automation_manager

def _get_screen_capture() -> ScreenCapture:
    global _screen_capture
    if _screen_capture is None:
        _screen_capture = ScreenCapture()
    return _screen_capture

class TypeTextHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return 'type_text'

    @property
    def supports_verification(self)->bool:
        return False
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if 'text' not in params:
            return (False, "Missing required parameter: 'text'")
        
        text = params['text']
        if text is None:
            return (False, "Parameter 'text' cannot be None")
         
        if 'interval' in params:
            try:
                interval = float(params['interval'])
                if interval<0:
                    return (False, "Parameter 'interval' must be non-negative")
            except (ValueError, TypeError):
                return (False, "Parameter 'interval' must be a number")
        return (True, None)
    
    def execute(self, params:Dict[str, Any], context: ExecutionContext)->ActionResult:
        try:
            text = str(params['text'])
            element_query = params.get("element_query")
            clear_first = params.get("clear_first", False)
            interval = params.get("interval", DEFULT_TYPE_INTERVAL)
            use_clipboard = params.get("use_clipboard", False)

            context.set_variable("typed_text", text)

            if element_query:
                result = self._type_into_element(
                    text, element_query, context, clear_first, interval
                )
                if result.success:
                    return result
                
            window = context.get_current_window_or_foreground()
            if not window:
                return ActionResult(
                    success=False,
                    error="No window available to type into",
                    method_used='none'
                )
            
            if clear_first:
                pyautogui.hotkey('ctrl','a')
                time.sleep(0.05)
                pyautogui.press('delete')
                time.sleep(0.05)

            if use_clipboard:
                self._type_via_clipboard(text)
                method='clipboard'
            else:
                pyautogui.write(text, interval=interval)
                method='pyautogui'
            
            return ActionResult(
                success=True,
                data={
                    'text_length':len(text),
                    'text_preview':text[:50] if len(text) > 50 else text,
                    'clear_first':clear_first
                },
                method_used=method
            )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception typing text: {str(e)}",
                method_used='pyautogui'
            )
        
    def _type_into_element(self, text:str, element_query:str,
                           context:ExecutionContext,
                           clear_first:bool,
                           interval:float)->ActionResult:
        window = context.get_current_window_or_foreground()
        if not window:
            return ActionResult(
                success=False,
                error= "No window context for element search",
                method_used='ui_automation'
            )

        cached_ref = context.get_element(element_query)
        if cached_ref and cached_ref.ui_element:
            element = cached_ref.ui_element
        
        else:
            ui_manager = _get_ui_automation()
            element = ui_manager.find_element(
                window.hwnd,
                name=element_query,
                partial_match=True
            )
        
        if not element:
            return ActionResult(
                success=False,
                error = f"Element '{element_query}' not found",
                method_used="ui_automation"
            )
        
        if not cached_ref:
            ref = ElementReference(
                source="ui_automation",
                bounding_box=element.bounding_box,
                ui_element=element
            )
            context.store_element(element_query, ref)
        
        ui_manager = _get_ui_automation()
        success = ui_manager.type_text(element=element, text=text, clear_first=clear_first)

        if success:
            return ActionResult(
                success=True,
                data= {
                    'text_length': len(text),
                    'element_name':element.name,
                    'element_type':element.control_type
                },
                method_used="ui_automation"
            )
        
        else:
            return ActionResult(
                success=False,
                error=f"Failed to type into element '{element_query}'",
                method_used='ui_automation'
            )
        
    def _type_via_clipboard(self, text:str)->None:
        import pyperclip

        try:
            old_clipboard = pyperclip.paste()
        except:
            old_clipboard = ""
        
        pyautogui.hotkey('ctr','v')
        time.sleep(0.05)

        try:
            pyperclip.copy(old_clipboard)
        except:
            pass

class HotkeyHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return 'hotkey'
    
    @property
    def supports_verification(self)->bool:
        return False
    
    def validate(self, params:Dict[str, Any])->Tuple[bool, Optional[str]]:
        if 'keys' not in params:
            return ( False, "Missing required parameter: 'keys'")
        
        keys = params['keys']
        if not isinstance(keys, (list, tuple)):
            return (False, "Parameter 'keys' must be a list")
        
        if len(keys) == 0:
            return (False, "Parameter 'keys' cannot be empty")
        
        for i,key in enumerate(keys):
            if not isinstance(key,str):
                return (False, f"key at index {i} must be a string")
            if key.strip() == "":
                return (False, f"Key at index {i} cannot be empty")
            
        return (True, None)
    
    def execute(self, params:Dict[str, Any], context: ExecutionContext)->ActionResult:
        try:
            keys = [str(k).lower().strip() for k in params['keys']]
            hold_time = params.get('hold_time',0)

            dangerous_combos = [
                ["alt", 'f4'],
                ['ctr;','w'],
                ['ctrl', 'shift','delete']
            ]
            keys_set = set(keys)
            for combo in dangerous_combos:
                if set(combo) == keys_set:
                    print(f"Executing potentially destrictive hotkey: {keys}")
                break

            context.set_variable("last_hotkey", keys)

            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys, interval=0.05)
            
            if hold_time >0:
                time.sleep(hold_time)

            return ActionResult(
                success=True,
                data={
                    'keys':keys,
                    'key_count': len(keys)
                }, 
                method_used="pyautogui"
            )
        
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception pressing hotkey: {str(e)}",
                method_used='pyautogui'
            )
    
class ClickHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return 'click'
    
    @property
    def supports_verification(self)->bool:
        return False
    
    @property
    def requires_visual_fallback(self)->bool:
        return True
    
    def validate(seld, params:Dict[str,Any])->Tuple[bool, Optional[str]]:
        has_query = 'query' in params
        has_coords = 'x' in params and 'y' in params

        if not has_query and not has_coords:
            return (False, "Missing required parameter: 'query' or 'x,y' coordinates")
        
        if has_query:
            query = params['query']
            if query is None or str(query).strip() == "":
                return (False, "Parameter 'query' cannot be empty")
        
        if has_coords:
            try:
                x = int(params['x'])
                y = int(params['y'])
                if x<0 and y <0:
                    return (False, "Coordinates cannot be negative")
            
            except ( ValueError, TypeError):
                return (False, "Parameter 'x' and 'y' must be integers")
            
        if 'click_type' in params:
            click_type = params['click_type']
            valid_types = ['left', 'right', 'double']
            if click_type not in valid_types:
                return (False, f"click_type must be one of: {valid_types}")
        
        return (True, None)
    
    def execute(self, params: Dict[str, Any], context: ExecutionContext)->ActionResult:
        try:
            query = params('query')
            x = params.get('x')
            y = params.get('y')
            click_type = params.get('click_type','left')
            use_visual_fallback = params.get('use_visual_fallback',True)
            element_type = params.get('element_type')
            if x is not None and y is not None:
                return self._click_at_coords(int(x),int(y), click_type)
            
            query = str(query).strip()
            cached_ref = context.get_element(query)
            if cached_ref:
                return self._click_cached_element(cached_ref, query, click_type)
            
            result = self._click_via_ui_automation(query,element_type,context,click_type)
            if result.success:
                return result
            
            if use_visual_fallback:
                result = self._click_via_visual(query,element_type,context, click_type)

                if result.success:
                    return result
            
            return ActionResult(
                success = False,
                error = f"Element '{query} not found via UI Automation or Visual Detection if use_visual_fallback else ''",
                method_used='none'
            )
        
        except Exception as e:
            return ActionResult(
                success=False,
                error = f"Exception during click: {str(e)}",
                method_used='none'
            )
        
    def _click_at_coords(self,x:int, y:int, click_type:str)->ActionResult:
        if click_type=='left':
            pyautogui.click(x,y)
        
        elif click_type == 'right':
            pyautogui.rightClick(x,y)
        
        elif click_type == 'double':
            pyautogui.doubleClick(x,y)

        time.sleep(DEFAULT_CLICK_PAUSE)

        return ActionResult(
            success=True,
            data={
                'x':x,
                'y':y,
                'click_type':click_type
            },
            method_used="pyautogui"
        )
    
    def _click_cached_element(self, cached_ref:ElementReference, query:str, click_type:str)->ActionResult:
        bbox = cached_ref.bounding_box
        center_x = bbox[0] + bbox[2]//2
        center_y = bbox[1] + bbox[3] //2

        result = self._click_at_coords(center_x,center_y, click_type)

        if result.success:  
            result.data['source'] = 'cached'
            result.data['element_query'] = query
            result.method_used = f"cached_{cached_ref.source}"
        
        return result
    
    def _click_via_ui_automation(self, query:str, element_type:Optional[str], context: ExecutionContext, click_type:str)->ActionResult:
        window = context.get_current_window_or_foreground()
        if not window:
            return ActionResult(
                success=False,
                error = "No window context for UI Automation search",
                method_used='ui_automaiton'
            )
        
        ui_manager = _get_ui_automation()
        element = ui_manager.find_element(
            window.hwnd,
            name = query,
            control_type=element_type,
            partial_match=True
        )
        
        if not element:
            return ActionResult(
                sucess = False,
                error = f"Element '{query}' not found via UI Automation",
                method_used="ui_automatoin"
            )
        
        ref = ElementReference(
            source='ui_automation',
            bounding_box=element.bounding_box,
            ui_element=element
        )
        context.store_element(query,ref)

        bbox = element.bounding_box
        center_x = bbox[0] + bbox[2] //2
        center_y = bbox[1] + bbox[3] //2

        success = ui_manager.click_element(element, 'left')
        if success:
            return ActionResult(
                success=True,
                data= {
                    'element_name': element.name,
                    'element_type': element.control_type,
                    'x':center_x,
                    'y':center_y,
                    'click_type':click_type
                },
                method_used='ui_automation'
            )
        result =  self._click_at_coords(center_x,center_y, click_type)
        if result.success:
            result.data["element_name"] = element.name
            result.data["element_type"] = element.control_type
            result.data["source"] = "ui_automation"
            result.method_used = "ui_automation_pyautogui"
        return result

    
    def _click_via_visual(self, query:str, element_type:Optional[str], context: ExecutionContext, click_type:str)->ActionResult:
        try:
            visual_analyzer = get_visual_analyzer()

            if not visual_analyzer.is_loaded():
                if not visual_analyzer.preload():
                    return ActionResult(
                        success=False,
                        error="Visual analyzer not available",
                        method_used='visual_fallback'
                    )
            
            screen_capture = _get_screen_capture()
            window = context.get_current_window_or_foreground()
            if window:
                screenshot = screen_capture.capture_window(window.hwnd, bring_to_front=True)   
            else: 
                screenshot = screen_capture.capture_active_window()
            if not screenshot:
                return ActionResult(
                    success=False,
                    error = "Failed to capture screenshot for visual search",
                    method_used="visual_fallback"
                )

            visual_element = visual_analyzer.find_element(
                screenshot,
                query,
                element_type=element_type
            )
            if not visual_element:
                return ActionResult(
                    success=False,
                    error = f"Element '{query}' not found via visual detection",
                    method_used="visual_fallback"
                )
            
            ref = ElementReference(
                source="visual",
                bounding_box=visual_element.bounding_box,
                visual_element=visual_element
            )
            context.store_element(query,ref)
            center_x,center_y = visual_element.center

            result = self._click_at_coords(center_x,center_y, click_type)

            if result.success:
                result.data['source'] = 'visual'
                result.data["element_label"] = visual_element.label
                result.data["element_type"] = visual_element.element_type
                result.data["confidence"] = visual_element.confidence
                result.method_used = "visual_fallback"
            return result
        
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Visual fallback error: {str(e)}",
                method_used="visual_fallback"
            )
        

class ScrollHander(ActionHandler):
    @property
    def action_name(self) -> str:
        return "scroll"
    
    @property
    def supports_verification(self) -> bool:
        return False
    
    def validate(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if "direction" not in params:
            return (False, "Missing required parameter: 'direction'")
        
        direction = params["direction"]
        if direction not in ["up", "down"]:
            return (False, "Parameter 'direction' must be 'up' or 'down'")
        
        if "amount" in params:
            try:
                amount = int(params["amount"])
                if amount <= 0:
                    return (False, "Parameter 'amount' must be positive")
                
            except (ValueError, TypeError):
                return (False, "Parameter 'amount' must be an integer")
        
        if "x" in params or "y" in params:
            if "x" not in params or "y" not in params:
                return (False, "Both 'x' and 'y' must be provided together")

            try:
                int(params["x"])
                int(params["y"])
            except (ValueError, TypeError):
                return (False, "Parameters 'x' and 'y' must be integers")
        
        return (True, None)
     
    def execute(self, params: Dict[str, Any], context: ExecutionContext)->ActionResult:
        try:
            direction = params['direction']
            amount = params.get('amount', DEFAULT_SCROLL_AMOUNT)
            x = params.get('x')
            y = params.get('y')
            
            scroll_amount = int(amount) if direction == 'up' else -int(amount)

            if x is not None and y is not None:
                pyautogui.moveTo(int(x), int(y))
                time.sleep(0.05)
            
            pyautogui.scroll(scroll_amount)

            return ActionResult(
                success=True,
                data={
                    'direction':direction,
                    'amount':amount,
                    'scroll_value':scroll_amount,
                    'x':x,
                    'y':y
                },
                method_used='pyautogui'
            )
        
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception during scroll: {str(e)}",
                method_used='pyautogui'
            )
        
INPUT_HANDLERS = [
    TypeTextHandler,
    HotkeyHandler,
    ClickHandler,
    ScrollHander
]

def get_input_handlers()->list:
    return [handler() for handler in INPUT_HANDLERS]

__all__ = [
    'TypeTextHandler',
    'HotkeyHandler', 
    'ClickHandler',
    'ScrollHandler',
    'INPUT_HANDLERS',
    'get_input_handlers',
]
            