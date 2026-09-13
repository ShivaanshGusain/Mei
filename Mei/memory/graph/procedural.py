"""
Procedural memory module.

Provides HNSW vector search for finding matching past goals and retrieving
their action chains for direct execution (LLM bypass).
"""

from typing import Optional, List, Dict, Any
from .connection import get_kuzu_connection
from .embedder import embed

def find_matching_goal(raw_command: str, threshold: float) -> Optional[Dict[str, Any]]:
      try:
          embedding = embed(raw_command)
          if all(v == 0.0 for v in embedding[:10]):
              return None

          conn = get_kuzu_connection()
          rows = conn.execute("""
            CALL QUERY_VECTOR_INDEX('Goal', 'goal_hnsw', $emb, 10)
            RETURN node.id AS id, node.raw_command AS raw_command,
                    node.action AS action, node.target AS target,
                    node.created_at AS created_at,
                    node.stability_score AS stability_score,
                    (1.0 - distance) AS confidence
            ORDER BY confidence DESC, node.created_at DESC
            LIMIT 1
        """, {"emb": embedding})

          if rows:
              best = rows[0]
              if best["confidence"] > threshold:
                  return best
          return None
      except Exception as e:
          print(f"[Memory] find_matching_goal error: {e}")
          return 

def get_procedure(goal_id: str) -> List[Dict[str, Any]]:
    """
    Returns the ordered Action chain for a goal via NEXT_ACTION traversal.
    
    Return shape per action:
    {'id': str, 'tool_name': str, 'parameters_json': str, 'duration_ms': float}
    """
    try:
        conn = get_kuzu_connection()
        rows = conn.execute("""
            MATCH (g:Goal {id: $gid})-[:ACHIEVED_BY]->(first:Action)
            MATCH p = (first)-[:NEXT_ACTION*0..20]->(a:Action)
            RETURN a.id AS id, a.tool_name AS tool_name,
                a.parameters_json AS parameters_json,
                a.duration_ms AS duration_ms,
                a.step_description AS step_description,
                a.step_domain AS step_domain,
                a.step_expected_output AS step_expected_output
            ORDER BY length(p)
        """, {"gid": goal_id})
        
        # Deduplicate results as path patterns might yield duplicate targets
        seen = set()
        procedure = []
        for row in rows:
            action_id = row.get('id')
            if action_id not in seen:
                seen.add(action_id)
                procedure.append(row)
        if len(procedure) == 1 and procedure[0].get("tool_name") == "wait":
          return []   # force fresh decomposition
        return procedure
    except Exception as e:
        print(f"Error in get_procedure: {e}")
        return []

def update_goal_stats(goal_id: str, success: bool, duration_ms: float) -> None:
    """Update replay statistics on an existing Goal node."""
    from datetime import datetime
    conn = get_kuzu_connection()
    if success:
        conn.execute(
            "MATCH (g:Goal {id: $gid}) "
            "SET g.success_count = coalesce(g.success_count, 0) + 1, "
            "    g.last_executed_at = $ts, "
            "    g.stability_score = 0.7 * coalesce(g.stability_score, 0.5) + 0.3 * 1.0",
            {"gid": goal_id, "ts": datetime.now().isoformat()}
        )
    else:
        conn.execute(
            "MATCH (g:Goal {id: $gid}) "
            "SET g.fail_count = coalesce(g.fail_count, 0) + 1, "
            "    g.last_executed_at = $ts, "
            "    g.stability_score = 0.7 * coalesce(g.stability_score, 0.5) + 0.3 * 0.0",
            {"gid": goal_id, "ts": datetime.now().isoformat()}
        )