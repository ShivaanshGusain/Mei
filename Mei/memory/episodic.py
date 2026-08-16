from .graph import find_matching_goal, get_kuzu_connection
from ..core.config import HistoricalHint
from ..core.task import Intent


class EpisodicMemory:
    def get_hints_for_intent(self, intent: Intent, max_hints: int = 5) -> list[HistoricalHint]:
        hints = []
        hints.extend(self._get_graph_hints(intent))
        hints.sort(key=lambda h: h.priority, reverse=True)  # FIX: was reversed=True
        return hints[:max_hints]
    
    def _get_graph_hints(self, intent: Intent) -> list[HistoricalHint]:
        # TODO (Micro-Planner): Update '_get_graph_hints' to process an
        # atomic intent from the Execution Queue to provide hyper-specific
        # step hints, rather than parsing the entire raw_command at once.
        
        match = find_matching_goal(intent.raw_command, threshold=0.75)
        if not match:
            return []
        
        conn = get_kuzu_connection()
        rows = conn.execute("""
            MATCH (g:Goal {id: $gid})-[:ACHIEVED_BY]->(a:Action)
                  -[:RESULTED_IN]->(o:Observation)
            RETURN o.success AS success, o.error AS error
        """, {"gid": match['id']})
        
        if not rows:
            return []
        
        failures = [r for r in rows if not r['success']]
        if len(failures) / len(rows) > 0.5:
            return [HistoricalHint(
                message=f"Similar command '{match['raw_command']}' failed "
                        f"{len(failures)}/{len(rows)} times. "
                        f"Last error: {failures[0].get('error', 'unknown')}",
                priority=100, source='graph_episode',
                confidence=match['confidence']
            )]
        else:
            return [HistoricalHint(
                message=f"Similar command '{match['raw_command']}' succeeded "
                        f"{len(rows)-len(failures)}/{len(rows)} times.",
                priority=70, source='graph_episode',
                confidence=match['confidence']
            )]