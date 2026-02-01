from typing import Dict, Any, Optional, List,Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from ..core.config import get_config,HistoricalHint, FailurePattern, SuccessPattern
from ..core.task import Intent
from .store import get_memory_store, MemoryStore

DEFAULT_HISTORY_LIMIT = 20
DEFAULT_SIMILAR_TASK_LIMIT = 5
DEFAULT_HINT_LIMIT = 5

MIN_EXECUTIONS_FOR_STATS = 3
LOW_SUCCESS_RATE_THRESHOLD = 0.6
HIGH_SUCCESS_RATE_THRESHOLD = 0.8

RECENT_WINDOW_HOURS = 24

HINT_PRIORITY_FAILURE_WARNING = 100
HINT_PRIORITY_RECOVERY_SUGGESTION = 90
HINT_PRIORITY_METHOD_RECOMMENDATION = 80
HINT_PRIORITY_SUCCESS_PATTERN = 70
HINT_PRIORITY_USER_PREFERENCE = 60
HINT_PRIORITY_GENERAL_CONTEXT = 50


class EpisodicMemory:

    def __init__(self):
        self._store: MemoryStore = get_memory_store()
    
    def get_hints_for_intent(self, intent:Intent, max_hints:int = DEFAULT_HINT_LIMIT)->List[HistoricalHint]:
        hints:List[HistoricalHint] = []

        failure_hints = self._get_failure_hints(intent)
        hints.extend(failure_hints)

        method_hints = self._get_method_hints(intent)
        hints.extend(method_hints)

        recovery_hints = self._get_recovery_hints(intent)
        hints.extend(recovery_hints)
        
        success_hints = self._get_preference_hints(intent)
        hints.extend(success_hints)

        preferenc_hints = self._get_preference_hints(intent)
        hints.extend(preferenc_hints)

        hints.sort(key = lambda h: h.priority, reversed = True)
        hints = hints[:max_hints]

        return hints
    
    def _get_failure_hints(self, intent:Intent)->List[HistoricalHint]:
        hints = []
        past_tasks = self._store.get_task_executions(
            intent_action=intent.action,
            intent_target=intent.target,
            limit=DEFAULT_HISTORY_LIMIT
        )

        if not past_tasks:
            return hints
        
        total = len(past_tasks)
        failures = [t for t in past_tasks if not t.get('success', True)]
        failure_count = len(failures)

        if total < MIN_EXECUTIONS_FOR_STATS:
            return hints
        
        failure_rate = failure_count/total

        if failure_rate > (1-LOW_SUCCESS_RATE_THRESHOLD):
            error_message = [
                f.get('failure_reason', 'Unknown error')
                for f in failures
                if f.get('failure_reason')
            ]
            
            common_error = self._get_most_common(error_message)

            success_pct = int((1-failure_rate)* 100)
            message = (
                f"Warning: '{intent.action}' for '{intent.target}'"
                f"has only {success_pct}% success rate"
                f"({total-failure_count}/{total} succeeded)"
            )

            if common_error:
                message +=f"Common error: '{common_error}'"

            hint = HistoricalHint(
                message=message,
                priority=HINT_PRIORITY_FAILURE_WARNING,
                source = f"failure_analysis",
                confidence=min(1.0, total/10),
                metadata={
                    'failure_rate':failure_rate,
                    'total_attempts':total,
                    'failure_count':failure_count,
                    'common_error':common_error
                }
            )
            hints.append(hint)

        recent_cutoff = datetime.now() - timedelta(hours=RECENT_WINDOW_HOURS)
        recent_failures = [
            f for f in failures
            if self._parse_timestamp(f.get('timestamp')) > recent_cutoff
        ]

        if len(recent_failures)>=2:
            message = (
                f"Recent issue: '{intent.action}' for '{intent.target}'"
                f"failed {len(recent_failures)} times in the last"
                f"{RECENT_WINDOW_HOURS} hours"
            )

            hint = HistoricalHint(
                message = message,
                priority=HINT_PRIORITY_FAILURE_WARNING + 10,
                source = 'recent_failure',
                confidence=0.9,
                metadata={
                    'recent_failure_count':len(recent_failures),
                    'window_hours':RECENT_WINDOW_HOURS
                }
            )
            hints.append(hint)
        
        return hints
    
    def _get_method_hints(self, intent:Intent)->List[HistoricalHint]:
        hints = []
        action_mapping = {
            'open':['launch_app', 'focus_window'],
            'close':['close_window', 'terminate_app'],
            'search':['type_text', 'hotkey', 'click'],
            'type':['type_text'],
            'click':['click'],
            'navigate':['navigate_url','type_text', 'hotkey']
        }

        relevent_actions = action_mapping.get(
            intent.action.lower(),
            [intent.action.lower()]
        )
        pass
