from typing import Dict, Any, Tuple, Optional

from ...core.task import ActionHandler
from ...core.config import ActionResult, VerifyResult, WindowInfo
from ...perception.System.windows import get_window_manager
from ..context import ExecutionContext

import win32gui

def _resolve_window(params: Dict[str,Any], context: ExecutionContext, require_match: bool = True) ->Tuple[Optional[WindowInfo], Optional[str]]:
    window_manager = get_window_manager()
    hwnd = params.get('hwnd')
    if hwnd is not None:
        window = window_manager.get_window_by_hwnd(int(hwnd))
        if window:
            return (window, None)
        else:
            return ( None, f"Window with hwnd {hwnd} not found")
        
    query  = params.get('query')
    if query:
        window = window_manager.find_window(str(query))
        if window:
            return (window, None)
        else:
            return ( None, f"Window matching '{query}' not found")
    if require_match:
        return (None, "Missing parameters: 'query' or 'hwnd'")
    if context.current_window:
        if win32gui.IsWindow(context.current_window.hwnd):
            return (context.current_window, None)
    
    foreground = window_manager.get_foreground_window()
    if foreground:
        return (foreground, None)
    
    return ( None, 'No window available')

class FocusWindowHandler(ActionHandler):
    @property
    def action_name(self)-> str:
        return 'focus_window'
    
    @property
    def supports_verification(self)->bool:
        return True
    
    def validate(self, params: Dict[str, Any])-> Tuple[bool, Optional[str]]:
        has_query = 'query' in params
        has_hwnd = 'hwnd' in params

        if not has_query and not has_hwnd:
            return (False, "Missing required parameter: 'query' or 'hwnd'")
        
        if has_query:
            query = params['query']
            if query is None or str(query).strip() == "":
                return (False,"Parameter 'query' cannot be empty")
        
        if has_hwnd:
            try:
                int(params['hwnd'])
            except ( ValueError, TypeError):
                return ( False, "Parameter 'hwnd' must be a valid integer")
        return ( True, None )
    
    def execute(self, params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
        try:
            window, error = _resolve_window(params=params, context= context, require_match= True)
            if window is None:
                return ActionResult(
                    success= False,
                    error = error,
                    method_used= 'window_manager'
                )
            window_manager = get_window_manager()
            success = window_manager.focus_window(window.hwnd)

            if success:
                context.set_current_window(window)
                return ActionResult(
                    success= True,
                    data = {
                        'hwnd': window.hwnd,
                        'title':window.title,
                        'process': window.process_name
                    },
                    method_used='window_manager'
                )
            else:
                return ActionResult(
                    success =False,
                    error = f'Failed to focus window: {window.title}',
                    method_used="window_manger"
                )
        except Exception as e:
            return ActionResult(
                success= False,
                error = f"Exception focusing window: {str(e)}",
                method_used='window_manager'
            )
    def verify(self, params: Dict[str, Any], context: ExecutionContext, result:ActionResult)->VerifyResult:
        hwnd = result.data.get('hwnd') if result.data else None
        if hwnd is None:
            return VerifyResult(
                verified=False,
                confidence=0.9,
                reason="No hwnd in result to verify"
            )
        if result.data.get("already_restored"):
            return VerifyResult(verified=True,
                                confidence=0.95,
                                reason="Window was already in normal state")
        try:
            import win32con
            is_minimized = win32gui.IsIconic(hwnd)
            placement = win32gui.GetWindowPlacement(hwnd)
            is_maximized = (placement[1] == win32con.SW_SHOWMAXIMIZED)

            if not is_minimized and not is_maximized:
                return VerifyResult(
                    verified=True,
                    confidence=0.95,
                    reason="Window confirmed as restored ( normal state )"
                )
            else:
                state = "minimized" if is_minimized else "maximized"
                return VerifyResult(
                    verified=False,
                    confidence=0.90,
                    reason = f"Window is still {state}"
                )
        except Exception as e:
            return VerifyResult(
                verified=False,
                confidence=0.5,
                reason = f"Verification error: {str(e)}"
            )

class MinimizeWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "minimize_window"

    @property
    def supports_verification(self)->bool:
        return True
    
    def validate(self, params:Dict[str,Any])->Tuple[bool, Optional[str]]:
        if 'query' in params:
            query = params['query']
            if query is not None and str(query).strip() == "":
                return (False, "Parameter 'query' cannot be empty string")
        if 'hwnd' in params:
            try:
                int(params['hwnd'])
            except ( ValueError, TypeError):
                return (False, "Parameter 'hwnd' must be a valid integer")
        return (True, None)
    
    def execute(self, params:Dict[str,Any], context:ExecutionContext)->ActionResult:
        try:
            window,error = _resolve_window(params, context,require_match=False)
            if window is None:
                return ActionResult(
                    success=False,
                    error=error if error is not None else "No window to minimize",
                    method_used="window_manager"
                )
            if window.is_minimized:
                return ActionResult(
                    success=True,
                    data={
                        'hwnd':window.hwnd,
                        'title':window.title,
                        'already_minimized':True
                    },
                    method_used="window_manager"
                )
            window_manager = get_window_manager()
            success = window_manager.minimize_window(window.hwnd)
            if success:
                if context.current_window and context.current_window.hwnd ==window.hwnd:
                    context.set_current_window(None)

                return ActionResult(
                    success=True,
                    data={
                        'hwnd':window.hwnd,
                        'title': window.title
                    },
                    method_used="window_manager"
                )
            else:
                return ActionResult(
                    success=False,
                    error = f"Failed to minimize window: {window.title}",
                    method_used="window_manager"
                )
        except Exception as e:
            return ActionResult(
                success= False,
                error = f"Exception minimized window: {str(e)}",
                method_used="window_manager"
            )

    def verify(self, params:Dict[str, Any], context: ExecutionContext, result: ActionResult)->VerifyResult:
        hwnd = result.data.get('hwnd') if result.data else None
        if hwnd is None:
            return VerifyResult(
                verified=False,
                confidence=0.9,
                reason="No hwnd in reault to verify"
            )
        if result.data.get('already_minimized'):
            return VerifyResult(
                verified=True,
                confidence=0.95,
                reason="Window was already Minimized"
            )
        try:
            is_minimized = win32gui.IsIconic(hwnd)
            if is_minimized:
                return VerifyResult(
                    verified=True,
                    confidence= 0.95,
                    reason = "Window confirmed as minimized"
                )
            else:
                return VerifyResult(
                    verified=False,
                    confidence=0.9,
                    reason="Window is not minimized"
                )
        except Exception as e:
            return VerifyResult(
                verified=False,
                confidence=0.95,
                reason=f"Verification error: {str(e)}"
            )

class MaximizeWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "maximize_window"
    
    @property
    def supports_verification(self)->bool:
        return True
    def validate(self, params:Dict[str, Any])->Tuple[bool, Optional[str]]:
        if 'query' in params:
            query = params['query']
            if query is not None and str(query).strip() == "":
                return (False, "Parameter 'query' cannot be empty string")
        if 'hwnd' in params:
            try:
                int(params['hwnd'])
            except(ValueError, TypeError):
                return (False, "Parameter 'hwnd' must be a valid integer")
        return (True, None)
    
    def execute(self, params:Dict[str,Any], context:ExecutionContext)->ActionResult:
        try:
            window, error = _resolve_window(params, context, require_match=False)
            if window is None:
                return ActionResult(
                    success=False,
                    error=error if error is not None else "No window to maximize",
                    method_used="window_manager"
                )
            if window.is_maximized:
                context.set_current_window(window)
                return ActionResult(
                    success=True,
                    data={
                        'hwnd':window.hwnd,
                        'title':window.title,
                        'already_maximized': True
                    },
                    method_used="window_manager"
                )
            window_manager = get_window_manager()
            success = window_manager.maximize_window(window.hwnd)
            if success:
                context.set_current_window(window)
                return ActionResult(
                    success =True,
                    data={
                        'hwnd':window.hwnd,
                        'title':window.title
                    },
                    method_used="window_manager"
                )
            else:
                return ActionResult(
                    success=False,
                    error=f"Failed to maximize window: {window.title}",
                    method_used="window_manager"
                )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception maximizing window: {str(e)}",
                method_used="window_manager"
            )
        
    def verify(self, params:Dict[str,Any], context:ExecutionContext, result: ActionResult)->VerifyResult:
        hwnd = result.data.get("hwnd") if result.data else None
        if hwnd is None:
            return VerifyResult(
                verified=False,
                confidence=0.9,                                            
                reason="No hwnd in result to verify"
            )
        if result.data.get("already_maximized"):
            return VerifyResult(
                verified=True,
                confidence=0.95,
                reason="Window was already maximized"
            )
        try:
            import win32con
            placement = win32gui.GetWindowPlacement(hwnd)
            is_maximized = (placement[1] == win32con.SW_SHOWMAXIMIZED)
            if is_maximized:
                return VerifyResult(
                    verified=True,
                    confidence=0.95,
                    reason="Window confirmed as maximized"
                )
            else:                                                          
                return VerifyResult(
                    verified=False,
                    confidence=0.90,
                    reason="Window is not maximized"
                )
        except Exception as e:
            return VerifyResult(
                verified=False,
                confidence=0.5,
                reason=f"Verification error: {str(e)}"
            )
    
class RestoreWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "restore_window"
    
    @property
    def supports_verification(self)->bool:
        return True
    
    def validate(self, params:Dict[str, Any])->Tuple[bool, Optional[str]]:
        if 'query' in params:
            query = params['query']
            if query is not None and str(query).strip() == "":
                return (False, "Parameter 'query' cannot be empty string")
        if 'hwnd' in params:
            try:
                int(params['hwnd'])
            except(ValueError, TypeError):
                return (False, "Parameter 'hwnd' must be a valid integer")
        return (True, None)
    
    def execute(self, params:Dict[str, Any], context:ExecutionContext)->ActionResult:
        try:
            window, error = _resolve_window(params, context, require_match=False)
            if window is None:
                return ActionResult(
                    success=False,
                    error=error or "No window to restore",
                    method_used="window_manager"
                )
            if not window.is_minimized and not window.is_maximized:
                context.set_current_window(window)
                return ActionResult(
                    success=True,
                    data={
                        'hwnd': window.hwnd,
                        'title': window.title,
                        'already_restored':True
                    },
                    method_used= "window_manager"
                )
            window_manager = get_window_manager()
            success = window_manager.restore_window(window.hwnd)
            if success:
                context.set_current_window(window)
                return ActionResult(
                    success=True,
                    data= {
                        'hwnd':window.hwnd,
                        'title':window.title,
                    },
                    method_used="window_manager"
                )
            else:
                return ActionResult(
                    success= False,
                    error=f"Failed to restore window: {window.title}",
                    method_used='window_manager'
                )
        except Exception as e:
            return ActionResult(
                success=False,
                error= f"Exeption restoring window: {str(e)}",
                method_used="window_manager"
            ) 
    def verify(self, params:Dict[str,Any], context:ExecutionContext, result: ActionResult)->VerifyResult:
        hwnd = result.data.get("hwnd") if result.data else None
        if hwnd is None:
            return VerifyResult(
                verified=False,
                confidence=0.9,                                            
                reason="No hwnd in result to verify"
            )
        if result.data.get("already_restored"):
            return VerifyResult(
                verified=True,
                confidence=0.95,
                reason="Window was already in normal state"
            )
        try:
            import win32con

            is_minimized = win32gui.IsIconic(hwnd)

            placement = win32gui.GetWindowPlacement(hwnd)
            is_maximized = (placement[1] == win32con.SW_SHOWMAXIMIZED)
            if not is_minimized and not is_maximized:
                return VerifyResult(
                    verified=True,
                    confidence=0.95,
                    reason="Window confirmed as restored"
                )
            else:  
                state = "minimized" if is_minimized else 'maximized'                                                        
                return VerifyResult(
                    verified=False,
                    confidence=0.90,
                    reason="Window is not still {state}"
                )
        except Exception as e:
            return VerifyResult(
                verified=False,
                confidence=0.5,
                reason=f"Verification error: {str(e)}"
            )    
class CloseWindowHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "close_window"
    
    @property
    def supports_verification(self)->bool:
        return True
    
    def validate(self, params:Dict[str,Any])->Tuple[bool, Optional[str]]:
        if 'query' in params:
            query = params['query']
            if query is not None and str(query).strip() == "":
                return (False,"Parameter 'query' cannot be empty")
        if 'hwnd' in params:
            try:
                int(params['hwnd'])
            except ( ValueError, TypeError):
                return (False, "Parameter 'hwnd' must be a valid integer")
        return (True, None)
    
    def execute(self, params: Dict[str, Any], context: ExecutionContext)->ActionResult:
        try:
            window, error = _resolve_window(params=params, context=context, require_match=False)
            if window is None:
                return ActionResult(
                    success = False,
                    error= error or "No window to close",
                    method_used="window_manager"
                )
            hwnd = window.hwnd
            title = window.title
            window_manager = get_window_manager()
            success = window_manager.close_window(hwnd)

            if success:
                if context.current_window and context.current_window.hwnd == hwnd:
                    context.set_current_window(None)
                return ActionResult(
                    success = True, 
                    data={
                        'hwnd': hwnd,
                        'title':title,
                        'closed':True
                    },
                    method_used="window_manager"
                )
            else:
                return ActionResult(
                    success=False,
                    error = f"Failed to close window: {title}",
                    method_used="window_manager"
                )
            
        except Exception as e:
            return ActionResult(
                success = False,
                error = f"Exception closing window: {str(e)}",
                method_used="window_manager"
            )
        
    def verify(self, params:Dict[str,Any], context:ExecutionContext, result: ActionResult)->VerifyResult:
        hwnd = result.data.get("hwnd") if result.data else None
        if hwnd is None:
            return VerifyResult(
                verified=False,
                confidence=0.9,
                reason = "No hwnd in result to verify"
            )
        try:
            import time
            time.sleep(0.2)

            window_exists = win32gui.IsWindow(hwnd)

            if not window_exists:
                return VerifyResult(
                    verified=True,
                    confidence=0.95,
                    reason= "Window confirned as closed ( no loger exists )"
                )
            else:
                return VerifyResult(
                    verified=False,
                    confidence = 0.85,
                    reason= "Window still exists ( may have unsaved change dialogies )"
                )
            
        except Exception as e:
            return VerifyResult(
                verified = False,
                confidence= 0.5,
                reason = f"Verificationerror: { str(e) }"
            )
    
WINDOW_HANDLERS = [
    FocusWindowHandler,
    MinimizeWindowHandler,
    MaximizeWindowHandler,
    RestoreWindowHandler,
    CloseWindowHandler
]

def get_window_handlers()->list:
    return [handler_class() for handler_class in WINDOW_HANDLERS]
    
    

if __name__ == "__main__":                                   
    import time                                              
    from ...core.task import Plan, Intent, Step, StepStatus 
    from ...action.context import ExecutionContext          
                                                             
    time.sleep(2)                                            
                                                             
    dummy_intent = Intent(                                   
        action="test",                                       
        target="windows",                                    
        raw_command="testing window handlers"                
    )                                                        
    dummy_plan = Plan(steps=[], strategy="test")             
    context = ExecutionContext(dummy_plan, dummy_intent)     
                                                             
    print("\nTEST 1: FocusWindowHandler")                    
    print("-" * 40)                                          
                                                             
    focus_handler = FocusWindowHandler()                     
    print(f"  action_name: {focus_handler.action_name}")     
    print(f"  supports_verification: {focus_handler.supports_verification}")
                                                             
    # Test validation - missing params                       
    is_valid, error = focus_handler.validate({})             
    print(f"  validate({{}}): valid={is_valid}, error={error}")    
    assert not is_valid, "Should fail with empty params"     
                                                             
    # Test validation - valid params                         
    is_valid, error = focus_handler.validate({"query": "Code"}) 
    print(f"  validate({{query:'Code'}}): valid={is_valid}")    
    assert is_valid, "Should pass with query"                
                                                             
    # Test execution                                         
    result = focus_handler.execute({"query": "Code"}, context)  
    print(f"  execute result: success={result.success}")     
    if result.success:                                       
        print(f"    hwnd: {result.data.get('hwnd')}")        
        print(f"    title: {result.data.get('title')}")      
        print(f"    context.current_window set: {context.current_window is not None}")
                                                             
        # Test verification                                  
        verify = focus_handler.verify({"query": "Code"}, context, result)
        print(f"  verify: verified={verify.verified}, confidence={verify.confidence}")
        print(f"    reason: {verify.reason}")                
    else:                                                    
        print(f"    error: {result.error}")                  
                                                             
    time.sleep(1)                                            
                                                            
    print("\nTEST 2: MinimizeWindowHandler")                 
    print("-" * 40)                                          
                                                             
    minimize_handler = MinimizeWindowHandler()               
                                                             
    # First focus notepad                                    
    focus_handler.execute({"query": "VSCODE"}, context)     
    time.sleep(0.5)                                          
                                                             
    # Test minimize with empty params (uses current window)  
    is_valid, error = minimize_handler.validate({})          
    print(f"  validate({{}}): valid={is_valid} (empty params OK)") 
                                                             
    result = minimize_handler.execute({}, context)           
    print(f"  execute (current window): success={result.success}") 
    if result.success:                                       
        print(f"    minimized: {result.data.get('title')}")  
        print(f"    context.current_window cleared: {context.current_window is None}")
                                                             
        verify = minimize_handler.verify({}, context, result)
        print(f"  verify: verified={verify.verified}")       
    else:                                                    
        print(f"    error: {result.error}")                  
                                                             
    time.sleep(1)                                            
                                                             
    print("\nTEST 3: RestoreWindowHandler")                  
    print("-" * 40)                                          
                                                             
    restore_handler = RestoreWindowHandler()                 
                                                             
    # Restore the minimized notepad                          
    result = restore_handler.execute({"query": "brave"}, context)
    print(f"  execute: success={result.success}")            
    if result.success:                                       
        print(f"    restored: {result.data.get('title')}")   
        print(f"    context.current_window set: {context.current_window is not None}")
                                                             
        verify = restore_handler.verify({"query": "brave"}, context, result)
        print(f"  verify: verified={verify.verified}")       
    else:                                                    
        print(f"    error: {result.error}")                  
                                                             
    time.sleep(1)                                            
                                                             
    print("\nTEST 4: MaximizeWindowHandler")                 
    print("-" * 40)                                          
                                                             
    maximize_handler = MaximizeWindowHandler()               
                                                             
    # Maximize calculator                                    
    result = maximize_handler.execute({"query": "calculator"}, context)
    print(f"  execute: success={result.success}")            
    if result.success:                                       
        print(f"    maximized: {result.data.get('title')}")  
                                                             
        verify = maximize_handler.verify({"query": "calculator"}, context, result)
        print(f"  verify: verified={verify.verified}")       
    else:                                                    
        print(f"    error: {result.error}")                  
                                                             
    time.sleep(1)                                            
                                                             
    # Restore calculator                                     
    restore_handler.execute({"query": "calculator"}, context)
                                                             
    print("\nTEST 5: CloseWindowHandler")                    
    print("-" * 40)                                          
    print("  Skipping close test to preserve your windows")  
    print("  To test manually:")                             
    print("    close_handler = CloseWindowHandler()")        
    print("    result = close_handler.execute({'query': 'notepad'}, context)")
                                                             
    close_handler = CloseWindowHandler()                     
    is_valid, error = close_handler.validate({"query": "notepad"}) 
    print(f"  validate: valid={is_valid}")                   
                                                             
    # ─────────────────────────────────────────────────────────────────   │
    # TEST 6: Error cases                                    
    # ─────────────────────────────────────────────────────────────────   │
    print("\nTEST 6: Error Cases")                           
    print("-" * 40)                                          
                                                             
    # Non-existent window                                    
    result = focus_handler.execute({"query": "nonexistent_window_xyz"}, context)
    print(f"  focus non-existent: success={result.success}") 
    print(f"    error: {result.error}")                      
                                                             
    # Invalid hwnd type                                      
    is_valid, error = focus_handler.validate({"hwnd": "not_a_number"})   
    print(f"  validate invalid hwnd: valid={is_valid}")      
    print(f"    error: {error}")                             
                                                             
    # Empty query                                            
    is_valid, error = focus_handler.validate({"query": ""})  
    print(f"  validate empty query: valid={is_valid}")       
    print(f"    error: {error}")                             
                                                             
    print("\nTEST 7: Handler Registration")                  
    print("-" * 40)                                          
                                                             
    handlers = get_window_handlers()                         
    print(f"  Total window handlers: {len(handlers)}")       
    for h in handlers:                                       
        print(f"    - {h.action_name} (verify: {h.supports_verification})")
                                                             
    print("\n" + "=" * 60)                                   
    print("WINDOW HANDLERS TEST COMPLETE")                   
    print("=" * 60)                                          
                                                             
