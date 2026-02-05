import time
from typing import Dict, Any, Optional, List, Type, Tuple
from datetime import datetime

from ..core.task import ActionHandler, Plan, Step, Intent, StepStatus
from ..core.config import ActionResult, VerifyResult, get_config
from ..core.events import EventType, Event, emit, subscribe, get_event_bus

from ..core.state import AgentState, get_state_machine


from .context import ExecutionContext
from  .debug.logger import get_execution_logger

from .handlers.window import get_window_handlers
from .handlers.app import get_app_handlers
from .handlers.input import get_input_handlers
from .handlers.navigation import get_navigation_handlers
from .handlers.utility import get_util_handers

DEFAULT_STEP_DELAY = 0.1
MAX_PLAN_DURATION = 300.0

LOG_VERIFICATION_FAILURES = True
VERIFY_STEPS = True

class PlanExecutor:
    def __init__(self, auto_subscribe: bool = True):
        self._handlers: Dict[str, ActionHandler] = {}
        self._register_all_handlers()

        self._logger = get_execution_logger()
        self._state_machine = get_state_machine()
        self._config = get_config()

        self._current_context: Optional[ExecutionContext] = None
        self._is_executing: bool = False
        if auto_subscribe:
            self.start()

    def _register_all_handlers(self)->None:
        all_handlers = []
        try:
            all_handlers.extend(get_window_handlers())
        except Exception as e:
            print(f"Failed to load window handlers: {e}")
        
        try:
            all_handlers.extend(get_app_handlers())
        except Exception as e:
            print(f"Failed to load app handlers: {e}")
        
        try:
            all_handlers.extend(get_input_handlers())
        except Exception as e:
            print(f"Failed to load input handlers: {e}")

        try:
            all_handlers.extend(get_navigation_handlers())
        except Exception as e:
            print(f"Failed to load navigation handlers: {e}")
        
        try:
            all_handlers.extend(get_util_handers())
        except Exception as e:
            print(f"Failed to load utility handlers: {e}")

        for handler in all_handlers:
            action_name = handler.action_name
            if action_name in self._handlers:
                print(f"Duplicate handler for '{action_name}'")
            self._handlers[action_name] = handler
        
        print(f"Registered {len(self._handlers)} handlers")
        for name in sorted(self._handlers.keys()):
            print(f" - {name}")

    def register_handler(self, handler: ActionHandler)->None:
        
        action_name = handler.action_name
        self._handlers[action_name] = handler
        print(f"Registered handler: {action_name}")

    def get_handler(self, action_name:str)->Optional[ActionHandler]:
        return self._handlers.get(action_name)
    
    def list_actions(self)->List[str]:
        return list(self._handlers.keys())
    
    def start(self)->None:
        subscribe(EventType.PLAN_CREATED, self._on_plan_created)
        print("Started - listening for PLAN_CREATED events")
    
    def stop(self)->None:
        self._is_executing = False
        print("Stopped")

    def _on_plan_created(self, event:Event)->None:
        plan = event.data.get('plan')
        intent = event.data.get('intent')
        
        if not plan or not intent:
            print("Error: PLAN_CREATED event missing plan or intent")
            emit(EventType.ERROR, source="Executor", error = "PLAN_CREATED event missing data")
            return 
        
        if self._is_executing:
            print("Warning: Already executing a plan, ignoring new plan")
            return
        self.execute_plan(plan,intent)

    def execute_plan(self, plan: Plan, intent: Intent) -> bool:
        self._is_executing = True
        plan_success = False
        failure_reason: Optional[str] = None

        if not self._state_machine.set_state(AgentState.EXECUTING):
            print("Warning: Could not transition to EXECUTING state")

        context = ExecutionContext(plan=plan, intent=intent)
        self._current_context = context

        print("Starting plan execution")
        print(f"Intent: {intent.action} -> {intent.target}")
        print(f"Strategy: {plan.strategy}")
        print(f"Steps: {len(plan.steps)}")

        try:
            for step_index,step in enumerate(plan.steps):
                if context.elapsed_time_ms() > MAX_PLAN_DURATION*1000:
                    failure_reason = "Plan Execution timeout"
                    break

                step_success, step_error = self._execute_step(step, step_index, context)

                if not step_success:
                    failure_reason = step_error
                    break

                if step_index < len(plan.steps) -1:
                    time.sleep(DEFAULT_STEP_DELAY)
            if failure_reason is None:
                plan_success = True

        except Exception as e:
            failure_reason = f"Unexpected exception: {str(e)}"
            print(f"Exception during execution: {e}")
            emit(EventType.ERROR, source="Executor", error = str(e))
            
        finally:
            execution_id = self._logger.log_execution(
                context= context,
                success=plan_success,
                failure_reason=failure_reason
            )

            if plan_success:
                emit(
                    EventType.PLAN_COMPLETED,
                    source='Executor',
                    plan = plan,
                    intent= intent,
                    execution_id = execution_id,
                    duration_ms = context.elapsed_time_ms()
                )
                print("Plan completed successfully")
            
            else:
                emit(
                    event_type=EventType.PLAN_FAILED,
                    source='Executor',
                    plan= plan,
                    intent=intent,
                    execution_id=execution_id,
                    error = failure_reason,
                    duration_ms = context.elapsed_time_ms()
                )
                print(f" Plan failed: {failure_reason}")
            
            self._state_machine.set_state(AgentState.IDLE)
        
            self._current_context = None
            self._is_executing = False

            print(f"Duration: {context.elapsed_time_ms():.0f}ms")
            print(f"Steps: {context.current_step_index}/{len(plan.steps)}")
            print(f"Success: {plan_success}")
            print(f"Execution ID: {execution_id}")

        return plan_success
    
    def _execute_step(self, step:Step, step_index:int, context: ExecutionContext)->Tuple[bool, Optional[str]]:
        context.current_step_index = step_index

        step.status = StepStatus.RUNNING
        step.started_at = datetime.now()

        print(f"Step { step_index +1}/{len(context.plan.steps)}: {step.action}")
        print(f"Description: {step.description}")
        print(f"Parameters: {step.parameters}")

        emit(
            EventType.PLAN_STEP_STARTED,
            source='Executor',
            step_index=step_index,
            action = step.action,
            parameters = step.parameters,
            description = step.description
        )

        handler = self.get_handler(step.action)

        if not handler:
            error_msg = f"No handler registered for action: '{step.action}'"
            step.status = StepStatus.FAILED
            step.error = error_msg
            step.completed_at = datetime.now()
            emit(
                EventType.PLAN_STEP_FAILED,
                source='Executor',
                step_index=step_index,
                action=step.action,                   
                parameters=step.parameters,           
                error=error_msg,
                method_used=None,                    
                duration_ms=0.0                       
            )

            return (False, error_msg)
        
        is_valid, validation_error = handler.validate(step.parameters)
        if not is_valid:
            error_msg = f"Validation failed: {validation_error}"
            step.status = StepStatus.FAILED
            step.error = error_msg
            step.completed_at = datetime.now()
            print(f"Validation failed: {validation_error}")
            emit(
                EventType.PLAN_STEP_FAILED,
                source='Executor',
                step_index=step_index,
                action=step.action,                   
                parameters=step.parameters,           
                error=error_msg,
                method_used=None,                     
                duration_ms=0.0                     
            )
            return (False, error_msg)

        try:
            result = handler.execute( step.parameters, context)
            context.add_step_result(result)
            step.result=result.data

            if not result.success:
                error_msg = result.error
                step.status = StepStatus.FAILED
                step.error = error_msg
                step.completed_at = datetime.now()
                print(f"Execution failed: {error_msg}")
                print(f"Method used: {result.method_used}")
                emit(
                    EventType.PLAN_STEP_FAILED,
                    source='Executor',
                    step_index=step_index,
                    action=step.action,                   # ADD
                    parameters=step.parameters,           # ADD
                    error=error_msg,
                    method_used=result.method_used,       # Already present
                    duration_ms=step_duration_ms,         # ADD
                    data=result.data                      # ADD: may contain partial info
                )                
                return (False, error_msg)
            
            verify_result: Optional[VerifyResult] = None
            if VERIFY_STEPS and handler.supports_verification:
                try:
                    verify_result = handler.verify(
                        step.parameters, context, result
                    )
                    step.verified = verify_result.verified
                    step.verification_method = 'handler_verify'

                    if verify_result.verified:
                        print(f"Verified ( confidence: {verify_result.confidence:.2f})")
                    else:
                        print(f"Verificaiton uncertain: {verify_result.reason}")
                        if LOG_VERIFICATION_FAILURES:
                            context.set_variable(
                                f"step_{step_index}_verify_failed",
                                verify_result.reason
                            )
                except Exception as e:
                    print(f"Verificatin error: {e}")

            step.status = StepStatus.COMPLETED
            step.completed_at = datetime.now()

            print(f"Completed ( {result.method_used})")
            if result.data:
                for key, value in list(result.data.items())[:3]:
                    print(f" {key}:{value}")
            step_duration_ms = (step.completed_at - step.started_at).total_seconds() * 1000
            emit(
                event_type=EventType.PLAN_STEP_COMPLETED,
                source="Executor",
                step_index=step_index,
                action=step.action,
                parameters=step.parameters,          
                method_used=result.method_used,
                duration_ms=step_duration_ms,         
                data=result.data,
                verified=step.verified,
                verify_confidence=verify_result.confidence if verify_result else None  
            )            
            return (True, None)
    
        except Exception as e:
            error_msg = f"Exception during execution: {str(e)}"
            step_duration_ms = (step.completed_at - step.started_at).total_seconds() * 1000
            step.status = StepStatus.FAILED                    
            step.error = error_msg                             
            step.completed_at = datetime.now()                 
            print(f"    ✗ Exception: {e}")                     
            emit(
                EventType.PLAN_STEP_FAILED,
                source="Executor",
                step_index=step_index,
                action=step.action,                   
                parameters=step.parameters,           
                error=error_msg,
                method_used=None,                    
                duration_ms=step_duration_ms          
            )           
            return (False, error_msg)                          


    def execute_single_action(self, action:str, parameters: Dict[str, Any])->ActionResult:
        handler = self.get_handler(action)
        if not handler:
            return ActionResult(
                success= False,
                error = f"No handler for action: {action}"
            )
        
        is_valid, error = handler.validate(parameters)
        if not is_valid:
            return ActionResult(
                success=False,
                error = f"Validation failed: {error}"
            )
        
        dummy_intent = Intent(
            action=action,
            target=None,
            parameters=parameters,
            confidence=0.1,
            raw_command=f"direct:{action}"
        )
        dummy_step = Step(
            id=f"direct_{action}",
            action=action,
            parameters=parameters,
            description=f"Direct execution of {action}"
        )

        dummy_plan = Plan(
            steps=[dummy_step],
            strategy="direct_execution",
            reasoning="Direct action execution"
        )

        context = ExecutionContext(plan = dummy_plan, intent= dummy_intent)

        try:
            return handler.execute(parameters,context)
        except Exception as e:
            return ActionResult(
                success=False,
                error = f"Exception: {str(e)}"
            )
        
    def get_current_context(self)->Optional[ExecutionContext]:
        return self._current_context
    

    @property
    def is_executing(self)->bool:
        return self._is_executing
    
_executor_instance:Optional[PlanExecutor] = None


def get_executor(auto_subscribe:bool = True)-> PlanExecutor:
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = PlanExecutor(auto_subscribe=auto_subscribe)
    return _executor_instance

def execute_plan(plan:Plan, intent:Intent)->bool:
    return get_executor().execute_plan(plan,intent)

def execute_action(action:str, parameters:Dict[str,Any])-> ActionResult:
    return get_executor().execute_single_action(action, parameters)

__all__ = [
    'PlanExecutor',
    'get_executor',
    'execute_plan',
    'execute_action',
]

if __name__ == "__main__":                                               
    """                                                                  
    Test the executor with sample actions and plans.                     
    """                                                                  
    import time                                                          
    from ..core.task import Plan, Step, Intent                           
                                                                         
    print("=" * 60)                                                      
    print("EXECUTOR TEST")                                               
    print("=" * 60)                                                      
                                                                         
    executor = PlanExecutor(auto_subscribe=False)                        
                                                                         
    print("\nTest 1: Registered Actions")                                
    print("-" * 40)                                                      
    actions = executor.list_actions()                                    
    for action in sorted(actions):                                       
        handler = executor.get_handler(action)                           
        print(f"  {action:20} verify={handler.supports_verification}")   
                                                                         
    print("\nTest 2: Execute Single Action (wait)")                      
    print("-" * 40)                                                      
    result = executor.execute_single_action(                             
        "wait",                                                          
        {"seconds": 1, "reason": "Test wait"}                            
    )                                                                    
    print(f"  Success: {result.success}")                                
    print(f"  Data: {result.data}")                                      
                                                                         
    print("\nTest 3: Execute Simple Plan")                               
    print("-" * 40)                                                      
                                                                         
    intent = Intent(                                                     
        action="test",                                                   
        target=None,                                                     
        parameters={},                                                   
        confidence=1.0,                                                  
        raw_command="test plan execution"                                
    )                                                                    
                                                                         
    plan = Plan(                                                         
        steps=[                                                          
            Step(                                                        
                id="step_1",                                             
                action="wait",                                           
                parameters={"seconds": 0.5, "reason": "Step 1"},         
                description="First wait"                                 
            ),                                                           
            Step(                                                        
                id="step_2",                                             
                action="wait",                                           
                parameters={"seconds": 0.5, "reason": "Step 2"},         
                description="Second wait"                                
            ),                                                           
        ],                                                               
        strategy="test_strategy",                                        
        reasoning="Testing executor"                                     
    )                                                                    
                                                                         
    success = executor.execute_plan(plan, intent)                        
    print(f"\n  Plan Success: {success}")                                
                                                                         
    print("\nTest 4: Plan with Invalid Action")                          
    print("-" * 40)                                                      
                                                                         
    bad_plan = Plan(                                                     
        steps=[                                                          
            Step(                                                        
                id="step_1",                                             
                action="nonexistent_action",                             
                parameters={},                                           
                description="This should fail"                           
            ),                                                           
        ],                                                               
        strategy="fail_test",                                            
        reasoning="Testing failure handling"                             
    )                                                                    
                                                                         
    success = executor.execute_plan(bad_plan, intent)                    
    print(f"\n  Plan Success: {success} (expected: False)")              
                                                                         
    print("\n" + "=" * 60)                                               
    print("EXECUTOR TEST COMPLETE")                                      
    print("=" * 60)                                                      

