"""
Episodic Memory — graph-native hint generation.

Queries Kùzu for similar past executions and returns HistoricalHints
for the planner to consider.
"""

from typing import List
from .graph import find_matching_goal, get_kuzu_connection
from ..core.config import HistoricalHint
from ..core.task import Intent


class EpisodicMemory:
    """Provides historical hints by querying the Kùzu episode graph."""

    def get_hints_for_intent(self, intent: Intent, max_hints: int = 5) -> List[HistoricalHint]:
        """
        Query the graph for similar past executions and generate hints.
        Uses a lower threshold (0.75) than bypass (0.92) — just for context.
        """
        hints: List[HistoricalHint] = []

        try:
            match = find_matching_goal(intent.raw_command, threshold=0.75)
            if not match:
                return hints

            # Query observations for this goal's action chain
            conn = get_kuzu_connection()
            rows = conn.execute("""
                MATCH (g:Goal {id: $gid})-[:ACHIEVED_BY]->(a:Action)
                      -[:RESULTED_IN]->(o:Observation)
                RETURN o.success AS success, o.error AS error
            """, {"gid": match['id']})

            if not rows:
                return hints

            failures = [r for r in rows if not r['success']]
            total = len(rows)
            failure_count = len(failures)

            if failure_count / total > 0.5:
                # Majority failed — warn the planner
                last_error = failures[0].get('error', 'unknown') if failures else 'unknown'
                hints.append(HistoricalHint(
                    message=(
                        f"Similar command '{match['raw_command']}' failed "
                        f"{failure_count}/{total} times. "
                        f"Last error: {last_error}"
                    ),
                    priority=100,
                    source='graph_episode',
                    confidence=match['confidence'],
                    metadata={
                        'matched_goal_id': match['id'],
                        'failure_rate': failure_count / total,
                    }
                ))
            else:
                # Majority succeeded — suggest the pattern
                hints.append(HistoricalHint(
                    message=(
                        f"Similar command '{match['raw_command']}' succeeded "
                        f"{total - failure_count}/{total} times."
                    ),
                    priority=70,
                    source='graph_episode',
                    confidence=match['confidence'],
                    metadata={
                        'matched_goal_id': match['id'],
                        'success_rate': (total - failure_count) / total,
                    }
                ))

        except Exception as e:
            print(f"[EpisodicMemory] Error getting graph hints: {e}")

        hints.sort(key=lambda h: h.priority, reverse=True)  # FIX: was reversed=True
        return hints[:max_hints]


# ── Singleton ──

_episodic_memory = None


def get_episodic_memory() -> EpisodicMemory:
    global _episodic_memory
    if _episodic_memory is None:
        _episodic_memory = EpisodicMemory()
    return _episodic_memory