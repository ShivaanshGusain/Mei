from typing import List, Dict, Any, Optional
from .connection import get_kuzu_connection
from .preference import get_preferences_by_category, get_preferences_for_prompt
from .procedural import find_matching_goal

def create_session(session_id: str, started_at: str) -> None:
    """
    MERGE a Session node. Simple upsert.
    """
    try:
        conn = get_kuzu_connection()
        query = """
        MERGE (s:Session {id: $sid})
        ON CREATE SET s.started_at = $ts, s.ended_at = ''
        ON MATCH SET s.started_at = $ts
        """
        conn.execute(query, {'sid': session_id, 'ts': started_at})
    except Exception as e:
        print(f"Error creating session: {e}")

def close_session(session_id: str, ended_at: str) -> None:
    """
    Set ended_at on the Session node.
    """
    try:
        conn = get_kuzu_connection()
        query = """
        MATCH (s:Session {id: $sid})
        SET s.ended_at = $ts
        """
        conn.execute(query, {'sid': session_id, 'ts': ended_at})
    except Exception as e:
        print(f"Error closing session: {e}")

def get_recent_goals(session_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Retrieve recent goals for a session, ordered newest-first.
    """
    try:
        conn = get_kuzu_connection()
        query = """
        MATCH (g:Goal)-[:PART_OF_SESSION]->(s:Session {id: $sid})
        RETURN g.id AS id, g.raw_command AS raw_command, g.action AS action, 
               g.target AS target, g.created_at AS created_at
        ORDER BY g.created_at DESC LIMIT $limit
        """
        results = conn.execute(query, {'sid': session_id, 'limit': limit})
        return results
    except Exception as e:
        print(f"Error getting recent goals: {e}")
        return []

def get_context_for_planner(session_id: str, intent_raw: str) -> Dict[str, Any]:
    """
    Builds the context dict passed to the LLM planner.
    This is the main integration point.
    """
    try:
        recent_goals = get_recent_goals(session_id)
        preferences = get_preferences_by_category('behavior')
        graph_preferences = get_preferences_for_prompt()
        
        # Use lower threshold (0.80) for planner hints rather than bypass (0.92)
        cached_plan = find_matching_goal(intent_raw, threshold=0.80)
        
        return {
            'session_id': session_id,
            'session_active': True,
            'recent_goals': recent_goals,
            'preferences': preferences,
            'graph_preferences': graph_preferences,
            'cached_plan': cached_plan
        }
    except Exception as e:
        print(f"Error getting context for planner: {e}")
        return {
            'session_id': session_id,
            'session_active': True
        }