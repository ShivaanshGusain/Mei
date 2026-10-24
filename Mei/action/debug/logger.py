import json
import os
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

from ...core.config import get_config


DEFAULT_LOG_DIR = 'data/execution_logs'
DEFAULT_LOG_FILE = 'execution_log.json'
MAX_LOG_ENTRIES = 1000


class ExecutionLogger:
    def __init__(self, log_dir: Optional[str] = 'logs', log_file: Optional[str] = None):
        config = get_config()
        if log_dir:
            self.log_dir = Path(log_dir)

        else:
            root = Path(config.root_dir) if config else Path(".") 
            self.log_dir = root / DEFAULT_LOG_DIR

        if log_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = f"execution_{timestamp}.log"
            self.log_file = f"execution_{timestamp}.json"
        else:
            self.log_file = log_file

        self.log_path = self.log_dir / self.log_file
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Warning: Could not create log dir {self.log_dir}: {e}")

        self._log_data = self._load_or_create_log()
        self._session_id = self._generate_session_id()

        self._save_log()

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
        if len(self._log_data.get('executions', [])) < MAX_LOG_ENTRIES:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f'execution_log_{timestamp}.json'
        archive_path = self.log_dir / archive_name

        try:
            if self.log_path.exists():
                self.log_path.rename(archive_path)
                print(f"Rotated log to {archive_name}")
        except IOError as e:
            print(f"Error rotating log: {e}")
            return 
    
    def log_execution(self, raw_command: str, success: bool, duration_ms: float,
                       step_results: List[Dict[str, Any]],
                       failure_reason: Optional[str] = None) -> str:
        """
        Records one full command execution as structured JSON, independent of
        Kùzu — useful for get_statistics()/get_failure_analysis() without a DB
        query, and as a plain-text-searchable execution history.

        `step_results` uses the same shape microplanner._commit_to_graph()
        already builds: [{"action", "parameters", "success", "method_used",
        "step_domain", ...}, ...] — NOT the old Intent/Plan/Step object shape
        this method used to (and would have crashed on: ExecutionContext no
        longer populates context.intent/context.plan).
        """
        execution_id = self._generate_execution_id()
        record = {
            'id': execution_id,
            'session_id': self._session_id,
            'timestamp': datetime.now().isoformat(),
            'success': success,
            'failure_reason': failure_reason,
            'duration_ms': duration_ms,
            'raw_command': raw_command,
            'step_count': len(step_results),
            'steps': [
                {
                    'index': i,
                    'action': s.get('action'),
                    'parameters': s.get('parameters'),
                    'success': s.get('success'),
                    'method_used': s.get('method_used'),
                    'step_domain': s.get('step_domain'),
                }
                for i, s in enumerate(step_results)
            ],
        }
        self._log_data['executions'].append(record)
        if success:
            self._log_data['metadata']['total_success'] = self._log_data['metadata'].get('total_success', 0) + 1
        else:
            self._log_data['metadata']['total_failures'] = self._log_data['metadata'].get("total_failures", 0) + 1

        self._rotate_if_needed()
        self._save_log()
        status = "Success" if success else "Failed"
        print(f"[ExecutionLogger] {status} {execution_id}: {raw_command[:40]!r} ({duration_ms:.0f}ms)")

        return execution_id

    def get_recent_executiosn(self, count: int = 10) -> List[Dict[str, Any]]:
        executions = self._log_data.get('executions',[])
        return list(reversed(executions[-count:]))
    
    def get_executions_by_intent(self, action:str, target: Optional[str] = None) -> List[Dict]:
        # Records carry no intent object — match on the tools the steps actually ran.
        matches = []
        for executions in self._log_data.get('executions', []):
            for step in executions.get('steps', []):
                if step.get('action') == action:
                    if target is None or target in str(step.get('parameters', {})):
                        matches.append(executions)
                        break
        return matches

    def get_failure_analysis(self)->Dict[str, Any]:
        # Failed records only contain the steps that succeeded before the
        # failure, so the failing step's index is len(steps) and its error is
        # the record-level failure_reason.
        failure_by_command = {}
        failure_by_step = {}
        error_messages = []
        total_failures = 0
        for executions in self._log_data.get("executions",[]):
            if executions.get('success'):
                continue
            total_failures +=1
            command = executions.get('raw_command') or 'unknown'
            failure_by_command[command] = failure_by_command.get(command,0) +1

            failed_index = len(executions.get('steps', []))
            failure_by_step[failed_index] = failure_by_step.get(failed_index,0) +1
            if executions.get('failure_reason'):
                error_messages.append(executions['failure_reason'])

        from collections import Counter
        error_counts = Counter(error_messages)
        common_errors = [err for err, count in error_counts.most_common(5)]
        return {
            'total_failures': total_failures,
            'failure_by_command': failure_by_command,
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
            # Count each execution once per distinct tool it used
            for action in {s.get('action') or 'unknown' for s in e.get('steps', [])}:
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