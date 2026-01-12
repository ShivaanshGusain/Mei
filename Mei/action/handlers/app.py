import time
from typing import Dict, Any, Tuple, Optional

from ...core.config import ActionResult, VerifyResult, AppHandlerConfig
from ...core.task import ActionHandler

from ...perception.System.process import get_process_manager
from ...perception.System.windows import get_window_manager

from ..context import ExecutionContext

class LaunchAppHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return "launch_app"
    
    @property
    def supports_verification(self)->bool:
        return True
    
    def validate(self, params:Dict[str,Any])->Tuple[bool, Optional[str]]:
        if 'app_name' not in params:
            return (False, "Missing required parameter: 'app_name'")
        
        app_name = params['app_name']
        if app_name is None or str(app_name).strip() == "":
            return (False, "Params 'app_name' cannot be empty")
        
        if 'wait_for_window' in params:
            if not isinstance(params['wait_for_window'], bool):
                pass
        return (True, None)
    
    def execute(self, params: Dict[str, Any],context:ExecutionContext)->ActionResult:
        try:
            app_name = str(params['app_name']).strip()
            wait_for_window = params.get('wait_for_window', True)
            focus_if_running = params.get('focus_if_running', True)
            
            process_manager = get_process_manager()
            window_manager = get_window_manager()

            is_running = process_manager.is_running(app_name)
            if is_running and focus_if_running:
                window = window_manager.find_window(app_name)
                if window:
                    success = window_manager.focus_window(window.hwnd)
                    if success:
                        context.set_current_window(window)
                        context.set_variable('launch_app', app_name)
                        return ActionResult(
                            success=True,
                            data={
                                'app_name':app_name,
                                'already_running':True,
                                'focus_existing':True,
                                'hwnd':window.hwnd,
                                'title':window.title,
                                'pid':window.pid
                            },
                            method_used="process_manager"
                        )
            pid = process_manager.launch(app_name)
            if pid is None:
                return ActionResult(
                    success = False,
                    error = f"Failed to launch '{app_name}'.\n App may not be installed or path not found",
                    method_used="process_manager"
                )
            context.set_variable('launched_app', app_name)
            context.set_variable('launched_pid', pid)
            
            window = None
            if wait_for_window:
                    window = self._wait_for_window(pid, app_name)        
            if window:
                window_manager.focus_window(window.hwnd)
                context.set_current_window(window)

            return ActionResult(
                success = True,
                data = {
                    'app_name':app_name,
                    'pid':pid,
                    'already_running': False,
                    'window_found': window is not None,
                    'hwnd': window.hwnd if window else None,
                    'title': window.title if window else None
                },
                method_used="process_manager"
            )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception Launching app: {str(e)}",
                method_used="process_manager"
            )

    
    def _wait_for_window(self, pid:int,app_name:str)->Optional['WindowInfo']:
        window_manager = get_window_manager()
        process_manager = get_process_manager()
        start_time = time.time()
        timeout = AppHandlerConfig.DEFAULT_LAUNCH_WAIT_SECONDS
        while (time.time()-start_time)<timeout:
            window =window_manager.get_window_by_pid(pid)
            if window:
                return window
            if not process_manager.is_running_pid(pid):
                fallback_win = window_manager.find_window(app_name)
                if fallback_win:
                    return fallback_win
            time.sleep(AppHandlerConfig.WINDOW_POLL_INTERVAL)
        return None
    
    def verify(self, params: Dict[str, Any], context: ExecutionContext, result: ActionResult)->VerifyResult:
        app_name = result.data.get('app_name') if result.data else None
        pid = result.data.get('pid') if result.data else None
        if not app_name:
            app_name = params.get('app_name')
        if not app_name:
            return VerifyResult(
                verified=False,
                confidence=0.9,
                reason="No app_name to verify"
            )
    
        try:
            window_manager = get_window_manager()
            process_manager = get_process_manager()

            if pid:
                win_by_pid = window_manager.get_window_by_pid(pid)
                if win_by_pid:
                    return VerifyResult(
                        verified=True,
                        confidence= 1.0,
                        reason= f"Confirmed window for PID {pid}"
                        )
                
            window = window_manager.find_window(app_name)
            if window:
                return VerifyResult(
                    verified= True, 
                    confidence=0.9,
                    reason= f"Found window matching '{app_name}'"
                    )

            if process_manager.is_running(app_name):
                return VerifyResult(
                    verified= True,
                    confidence= 0.7, 
                    reason= f"Process '{app_name}' is running"
                    )

            return VerifyResult(verified= False, 
                                confidence=0.9,
                                reason= f"No process or window found for '{app_name}'"
                                )

        except Exception as e:
            return VerifyResult(
                verified=False,
                confidence= 0.5,
                reason= f"Verification error: {str(e)}"
                )        
            

class TerminateAppHandler(ActionHandler):
    @property
    def action_name(self)->str:
        return 'terminate_app'

    @property
    def supports_verification(self)->bool:
        return True
    
    def validate(self, params:Dict[str, Any])->Tuple[bool, Optional[str]]:
        has_app_name = 'app_name' in params
        has_pid = 'pid' in params

        if not has_app_name and not has_pid:
            return (False, "missing required parameters: 'app_name' or 'pid'")
        
        if has_app_name:
            app_name = params['app_name']
            if app_name is None or str(app_name).strip() == "":
                return (False, "Parameter 'app_name' cannot be empty'")
        
        if has_pid:
            try:
                pid = int(params['pid'])
                if pid <=0:
                    return ( False, "Parameter 'pid' must be positive")
            except( ValueError, TypeError):
                return (False, "Parameter 'pid' bust be a valid integer'")
        
        return (True, None)

    def execute(self, params: Dict[str, Any], context: ExecutionContext) -> ActionResult:
        try:
            process_manager = get_process_manager()
            pid = params.get('pid')
            app_name = params.get('app_name')

            if pid is not None:
                try:
                    pid = int(pid)
                    if context.current_window and context.current_window.pid == pid:
                        context.set_current_window(None)
                        
                    process = process_manager.get_process_by_pid(pid)
                    process_name = process.name if process else "unknown"

                    if process_manager.terminate(pid):
                        return ActionResult(
                            success=True, 
                            data={'terminated_by': 'pid', 'pid': pid, 'process_name': process_name}, 
                            method_used='process_manager'
                        )
                    else:
                        return ActionResult(
                            success=False, 
                            error=f"Failed to terminate process {pid}", 
                            method_used="process_manager"
                        )
                except ValueError:
                    pass

            if app_name:
                app_name = str(app_name).strip()
                
                if not process_manager.is_running(app_name):
                    return ActionResult(
                        success=True,
                        data={
                            'terminated_by': 'app_name',
                            'app_name': app_name,
                            'already_not_running': True,
                            'count': 0
                        },
                        method_used='process_manager'
                    )

                should_clear_window = False
                if context.current_window:
                    current_process = context.current_window.process_name.lower()
                    target_app = app_name.lower()
                    
                    if target_app in current_process:
                        should_clear_window = True

                terminated_count = process_manager.terminate_by_name(app_name)
                
                if terminated_count > 0:
                    if should_clear_window:
                        context.set_current_window(None)
                    
                    return ActionResult(
                        success=True,
                        data={
                            'terminated_by': "app_name",
                            'app_name': app_name,
                            'count': terminated_count
                        },
                        method_used='process_manager'
                    )
                else:
                    return ActionResult(
                        success=False,
                        error=f"Failed to terminate app: {app_name}",
                        method_used="process_manager"
                    )

            return ActionResult(
                success=False, 
                error=f"No valid target (pid or app_name) provided", 
                method_used="process_manager"
            )

        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Exception terminating app: {str(e)}",
                method_used="process_manager"
            )
    def verify(self, params:Dict[str,Any], context:ExecutionContext, result:ActionResult)->VerifyResult:
        time.sleep(0.5)
        if result.data and result.data.get("already_not_running"):
            return VerifyResult(
                verified=True,
                confidence=0.95,
                reason="App was already not running"
            )
        time.sleep(0.3)
        process_manager = get_process_manager()
        try:
            app_name = None
            pid = None
            if result.data:
                app_name = result.data.get("app_name")
                pid = result.data.get("pid")
            if not app_name and not pid:
                app_name = params.get("app_name")
                pid = params.get("pid")
            
            if pid:
                process = process_manager.get_process_by_pid(int(pid))
                if process is None:
                    return VerifyResult(
                        verified=True,
                        confidence=0.95,
                        reason=f"Process {pid} no longer exists"
                    )
                else:
                    return VerifyResult(
                        verified=False,
                        confidence=0.90,
                        reason=f"Process {pid} still running"
                    )
            
            if app_name:
                is_running = process_manager.is_running(app_name)
                if not is_running:
                    return VerifyResult(
                        verified=True,
                        confidence=0.95,
                        reason=f"App '{app_name}' is no longer running"
                    )
                else:
                    return VerifyResult(
                        verified=False,
                        confidence=0.90,
                        reason=f"App '{app_name}' is still running"
                    )
            return VerifyResult(
                verified=False,
                confidence=0.5,
                reason="No app_name or pid to verify"
            )
        except Exception as e:
            return VerifyResult(
                verified=False,
                confidence=0.5,
                reason = f"Verification error: {str(e)}"
            )
    
APP_HANDLERS = [
    LaunchAppHandler,
    TerminateAppHandler
]

def get_app_handlers()->list:
    return [handler_class() for handler_class in APP_HANDLERS]

if __name__ == "__main__":                                                
    """                                                                   
    Test app handlers.                                                    
                                                                          
    This test will:                                                       
    1. Launch Notepad                                                     
    2. Verify it's running                                                
    3. Terminate it                                                       
    4. Verify it's gone                                                   
    """                                                                   
    import time                                                           
    from ...core.task import Plan, Intent                                
    from ...action.context import ExecutionContext                       
                                                                          
    print("=" * 60)                                                       
    print("APP HANDLERS TEST")                                            
    print("=" * 60)                                                       
                                                                          
    # Create minimal context for testing                                  
    dummy_intent = Intent(                                                
        action="test",                                                    
        target="apps",                                                    
        raw_command="testing app handlers"                                
    )                                                                     
    dummy_plan = Plan(steps=[], strategy="test")                          
    context = ExecutionContext(dummy_plan, dummy_intent)                  
                                                                          
    # ─────────────────────────────────────────────────────────────────   
    # TEST 1: LaunchAppHandler - Validation                               
    # ─────────────────────────────────────────────────────────────────   
    print("\nTEST 1: LaunchAppHandler - Validation")                      
    print("-" * 40)                                                       
                                                                          
    launch_handler = LaunchAppHandler()                                   
    print(f"  action_name: {launch_handler.action_name}")                 
    print(f"  supports_verification: {launch_handler.supports_verification}")
                                                                          
    # Missing app_name                                                    
    is_valid, error = launch_handler.validate({})                         
    print(f"  validate({{}}): valid={is_valid}, error={error}")           
    assert not is_valid                                                   
                                                                          
    # Empty app_name                                                      
    is_valid, error = launch_handler.validate({"app_name": ""})           
    print(f"  validate({{app_name:''}}): valid={is_valid}")               
    assert not is_valid                                                   
                                                                          
    # Valid app_name                                                      
    is_valid, error = launch_handler.validate({"app_name": "brave"})    
    print(f"  validate({{app_name:'notepad'}}): valid={is_valid}")        
    assert is_valid                                                       
                                                                          
    # ─────────────────────────────────────────────────────────────────   
    # TEST 2: LaunchAppHandler - Execute                                  
    # ─────────────────────────────────────────────────────────────────   
    print("\nTEST 2: LaunchAppHandler - Execute")                         
    print("-" * 40)                                                       
                                                                          
    result = launch_handler.execute({"app_name": "brave"}, context)     
    print(f"  execute result: success={result.success}")                  
    if result.success:                                                    
        print(f"    app_name: {result.data.get('app_name')}")             
        print(f"    pid: {result.data.get('pid')}")                       
        print(f"    already_running: {result.data.get('already_running')}")
        print(f"    window_found: {result.data.get('window_found')}")     
        print(f"    hwnd: {result.data.get('hwnd')}")                     
        print(f"    title: {result.data.get('title')}")                   
        print(f"    context.current_window: {context.current_window is not None}")
        print(f"    context.variables['launched_app']: {context.get_variable('launched_app')}")
                                                                          
        # Verify                                                          
        verify = launch_handler.verify({"app_name": "brave"}, context, result)
        print(f"  verify: verified={verify.verified}, confidence={verify.confidence}")
        print(f"    reason: {verify.reason}")                             
    else:                                                                 
        print(f"    error: {result.error}")                               
                                                                          
    time.sleep(1)                                                         
                                                                          
    # ─────────────────────────────────────────────────────────────────   
    # TEST 3: LaunchAppHandler - Already Running                          
    # ─────────────────────────────────────────────────────────────────   
    print("\nTEST 3: LaunchAppHandler - Already Running")                 
    print("-" * 40)                                                       
                                                                          
    result = launch_handler.execute({"app_name": "brave"}, context)     
    print(f"  execute result: success={result.success}")                  
    print(f"    already_running: {result.data.get('already_running')}")   
    print(f"    focused_existing: {result.data.get('focused_existing')}")  
                                                                          
    time.sleep(1)                                                         
                                                                          
    # ─────────────────────────────────────────────────────────────────   
    # TEST 4: TerminateAppHandler - Validation                            
    # ─────────────────────────────────────────────────────────────────   
    print("\nTEST 4: TerminateAppHandler - Validation")                   
    print("-" * 40)                                                       
                                                                          
    terminate_handler = TerminateAppHandler()                             
    print(f"  action_name: {terminate_handler.action_name}")              
                                                                          
    # Missing both params                                                 
    is_valid, error = terminate_handler.validate({})                      
    print(f"  validate({{}}): valid={is_valid}")                          
    assert not is_valid                                                   
                                                                          
    # Valid app_name                                                      
    is_valid, error = terminate_handler.validate({"app_name": "brave"}) 
    print(f"  validate({{app_name:'brave'}}): valid={is_valid}")        
    assert is_valid                                                       
                                                                          
    # Valid pid                                                           
    is_valid, error = terminate_handler.validate({"pid": 12345})          
    print(f"  validate({{pid:12345}}): valid={is_valid}")                 
    assert is_valid                                                       
                                                                          
    # Invalid pid                                                         
    is_valid, error = terminate_handler.validate({"pid": "not_a_number"}) 
    print(f"  validate({{pid:'not_a_number'}}): valid={is_valid}")        
    assert not is_valid                                                   
                                                                          
    # ─────────────────────────────────────────────────────────────────   
    # TEST 5: TerminateAppHandler - Execute                               
    # ─────────────────────────────────────────────────────────────────   
    print("\nTEST 5: TerminateAppHandler - Execute")                      
    print("-" * 40)                                                       
                                                                          
    print("  (About to terminate notepad)")                               
    result = terminate_handler.execute({"app_name": "brave"}, context)  
    print(f"  execute result: success={result.success}")                  
    if result.success:                                                    
        print(f"    terminated_by: {result.data.get('terminated_by')}")   
        print(f"    count: {result.data.get('count')}")                   
        print(f"    context.current_window cleared: {context.current_window is None}")
                                                                          
        # Verify                                                          
        verify = terminate_handler.verify({"app_name": "brave"}, context, result)
        print(f"  verify: verified={verify.verified}, confidence={verify.confidence}")
        print(f"    reason: {verify.reason}")                             
    else:                                                                 
        print(f"    error: {result.error}")                               
                                                                          
    # ─────────────────────────────────────────────────────────────────   
    # TEST 6: TerminateAppHandler - Already Not Running                   
    # ─────────────────────────────────────────────────────────────────   
    print("\nTEST 6: TerminateAppHandler - Already Not Running")          
    print("-" * 40)                                                       
                                                                          
    result = terminate_handler.execute({"app_name": "brave"}, context)  
    print(f"  execute result: success={result.success}")                  
    print(f"    already_not_running: {result.data.get('already_not_running')}")
                                                                          
    # ─────────────────────────────────────────────────────────────────   
    # TEST 7: Error cases                                                 
    # ─────────────────────────────────────────────────────────────────   
    print("\nTEST 7: Error Cases")                                        
    print("-" * 40)                                                       
                                                                          
    # Non-existent app                                                    
    result = launch_handler.execute({"app_name": "nonexistent_app_xyz"}, context)
    print(f"  launch non-existent: success={result.success}")             
    print(f"    error: {result.error}")                                   
                                                                          
    # ─────────────────────────────────────────────────────────────────   
    # TEST 8: get_app_handlers()                                          
    # ─────────────────────────────────────────────────────────────────   
    print("\nTEST 8: Handler Registration")                               
    print("-" * 40)                                                       
                                                                          
    handlers = get_app_handlers()                                         
    print(f"  Total app handlers: {len(handlers)}")                       
    for h in handlers:                                                    
        print(f"    - {h.action_name} (verify: {h.supports_verification})")
                                                                          
    print("\n" + "=" * 60)                                                
    print("APP HANDLERS TEST COMPLETE")                                   
    print("=" * 60)                                                       
