import json
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

from ...core.config import get_config, ActionResult
from ...core.task import Plan, Intent, StepStatus
from ..context import ExecutionContext


DEFAULT_LOG_DIR = 'data/exection_logs'
DEFAULT_LOG_FILE = 'execution_log.json'
MAX_LOG_ENTRIES = 1000


class ExecutionLogger:
    def __init__(self, log_dir: Optional[str] = None, log_file: Optional[str] = None):
        config = get_config()
        self.log_dir = Path(log_dir) if log_dir else Path(config.root_dir) / DEFAULT_LOG_DIR
        self.log_file = log_file if log_file else DEFAULT_LOG_FILE
        self.log_path = self.log_dir / log_file

        self.log_dir.mkdir(parents = True, exist_ok= True)

        self._log_data = self._load_or_create_log()
        self._session_id = self._generate_session_id()

    def _generate_session_id(self)-> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"session_{timestamp}"
    
    def _generate_execution_id(self)->str:
        import uuid
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique = uuid.uuid4().hex[:5]
        return f"exec_{timestamp}_{unique}"
    
    def _load_or_create_log(self)->Dict[str,Any]:
        if self.log_path.exists():
            try:
                with open(self.log_path, 'r', encoding= 'utf-8') as f:
                    data = json.load(f)
                    if 'executions' in data and 'metadata' in data:
                        return data
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading log file: {e}")

        return {
            "executions": [],
            "metadata": { 
                "version":'1.0',
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'total_executions': 0,
                'total_success': 0,
                'total_failures': 0
            }
        }
    
    def _save_log(self)->bool:
        self._log_data['metadata']['last_updated'] = datetime.now().isoformat()
        self._log_data['metadata']['total_executions'] = len(self._log_data['executions'])

        try:
            with open(self.log_path, 'w', encoding='utf-8') as f:
                json.dump(self._log_data, f, indent=2, default= str)
            return True
        except IOError as e:
            print(f"Error saving log file: {e}")
            return False
    
    def _rotate_if_needed(self)->None:
        if len(self._log_data['execution']) < MAX_LOG_ENTRIES:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f'execution_log_{timestamp}.json'
        archive_path = self.log_dir / archive_name

        try:
            if self.log_path.exists():
                self.log_path.rename(archive_path)
                print(f"Rotated log to {archive_name}")
        except IOError as e:
            print("Error rotating log: {e}")
            return 
    
    def log_execution(self, context:ExecutionContext, success:bool, failure_reason: Optional[str] = None)-> str:
        execution_id = self._generate_execution_id()
        record = {
            'id': self._session_id,
            'timestamp': datetime.now().isoformat(),
            'success': success,
            'failure_reason':failure_reason,
            'duration_ms': context.elapsed_time_ms(),
            'intent':{
                'action':context.intent.action,
                'target': context.intent.target,
                'parameters': context.intent.parameters,
                'raw_command': context.intent.raw_command,
                'confidence':context.intent.confidence
            },
            'plan':{
                'strategy': context.plan.strategy,
                'reasoning': context.plan.reasoning,
                'step_count': len(context.plan.steps),
                'steps':[
                    {
                        'index': i,
                        'action': step.action,
                        'parameters':step.parameters,
                        'description': step.description,
                        'status': step.status.name if step.status else "UNKNOWN"
                    }
                    for i, step in enumerate(context.plan.steps)
                ]
            },
            'step_results': [ 
                {
                    'step_index':  i,
                    'success': result.success,
                    'method_used': result.method_used,
                    'error': result.error,
                    'data_key': list(result.data.keys()) if result.data else []
                }
                for i, result in enumerate(context.step_results)
            ],
            'final_context': {
                'current_window': {
                    'hwnd': context.current_window.hwnd,
                    'title': context.current_window.title,
                    'process': context.current_window.process_name
                } if context.current_window else None,
                'variables': context.variables,
                'cached_element': list(context._found_elements.keys())
            }
        }
        self._log_data['executions'].append(record)
        if success:
            self._log_data['metadata']['total_successes'] = self._log_data['metadata'].get('total_successes', 0) +1
        else:
            self._log_data['metadata']['total_failures'] = self._log_data['metadata'].get("total_failures", 0 ) + 1

        self._rotate_if_needed()
        self._save_log()
        status = "Success" if success else "Failed"
        print(f" {status} execution id: {execution_id}, {context.intent.raw_command[:40]}, {context.elapsed_time_ms():.0f}ms")

        return execution_id
    
    def log_step(self, context: ExecutionContext, step_index: int, result: ActionResult) -> None:
        step = context.plan.steps[step_index] if step_index < len(context.plan.steps) else None
        if not step:
            return 

        status = "Success" if result.success else "Fail"
        print(f"Step { step_index + 1} / { len(context.plan.steps)} { status} { step.action}, {   result.method_used}")
        if result.error:
            print(f"Error: {result.error}")

    def get_recent_executiosn(self, count: int = 10) -> List[Dict[str, Any]]:
        executions = self._log_data.get('executions',[])
        return list(reversed(executions[-count:]))
    
    def get_executions_by_intent(self, action:str, target: Optional[str] = None) -> List[Dict]:
        matches = []
        for executions in self._log_data.get('executions', []):
            intent = executions.get('intent', {})
            if intent.get('action') == action:
                if target is None or intent.get('target') == target:
                    matches.append(executions)
        return matches
    
    def get_failure_analysis(self)->Dict[str, Any]:
        failure_by_action = {}
        failure_by_step = {}
        error_messages = []
        total_failures = 0
        for executions in self._log_data.get("executions",[]):
            if executions.get('success'):
                continue
            total_failures +=1
            action = executions.get('intent',{}).get('action','unknown')
            failure_by_action[action] = failure_by_action(action,0) +1
            
            for i,step_results in enumerate(executions.get("Step_results", [])):
                if not step_results.get('success'):
                    failure_by_step[i] = failure_by_step(i,0) +1
                    if step_results.get("error"):
                        error_messages.append(step_results['error'])
                    break
        
        
        from collections import Counter
        error_counts = Counter(error_messages)
        common_errors = [err for err, count in error_counts.most_common(5)]
        return {
            'total_failures': total_failures,
            'failure_by_action': failure_by_action,
            'failure_by_step': failure_by_step,
            'common_errors': common_errors
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        executions = self._log_data.get("executions", [])
        if not executions:
            return {
                'total_executions': 0,
                'success_rate': 0.0,
                'average_duration_ms': 0.0,
                'executions_by_action': {}
            }
        
        total = len(executions)
        success = sum(1 for e in executions if e.get('success'))
        total_duration = sum(e.get('duration_ms', 0) for e in executions)
        by_action = {}
        for e in executions:
            action = e.get('intent', {}).get('action', 'unknown')
            by_action[action] = by_action.get(action,0) + 1
            
        return {
            'total_executions': total,
            'success_rate': (success/total) * 100 if total > 0 else 0 ,
            'average_duration_ms': total_duration / total if total > 0 else 0,
            'executions_by_action': by_action
        }
    

_logger_instance: Optional[ExecutionLogger] = None

def get_execution_logger()->ExecutionLogger:
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = ExecutionLogger()
    return _logger_instance