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
                    node.verified_total_count AS verified_total_count,
                    node.verified_reliability AS verified_reliability,
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

def update_goal_stats(goal_id: str, success: bool, duration_ms: float, verified: bool = False) -> None:
    """
    Update replay statistics on an existing Goal node.

    `verified` distinguishes "the steps ran without error" from "a real
    domain-specific check confirmed the outcome" (see
    cognition.planning.evaluator.sequence_has_verified_evidence /
    is_verifiable_domain).

    `verified_reliability` is an EMA over verified attempts only, using the
    same decay as `stability_score` — deliberately NOT a lifetime
    success/total ratio. A lifetime ratio's denominator only grows, so a goal
    that was reliable for months and then starts failing (e.g. the target
    website changed) would barely move: a handful of new failures can't
    outvote hundreds of accumulated historical successes. An EMA actually
    drops when recent attempts fail, which is what Tier 1's gate needs to mean
    something. `verified_total_count` is kept only as a lifetime "has this
    ever actually been verified at all" counter, not as a ratio denominator.
    """
    from datetime import datetime
    conn = get_kuzu_connection()
    outcome = 1.0 if success else 0.0
    set_clauses = [
        "g.last_executed_at = $ts",
        "g.stability_score = 0.7 * coalesce(g.stability_score, 0.5) + 0.3 * $outcome",
    ]
    if success:
        set_clauses.append("g.success_count = coalesce(g.success_count, 0) + 1")
    else:
        set_clauses.append("g.fail_count = coalesce(g.fail_count, 0) + 1")
    if verified:
        set_clauses.append("g.verified_total_count = coalesce(g.verified_total_count, 0) + 1")
        set_clauses.append("g.verified_reliability = 0.7 * coalesce(g.verified_reliability, 0.5) + 0.3 * $outcome")
        if success:
            set_clauses.append("g.verified_success_count = coalesce(g.verified_success_count, 0) + 1")

    conn.execute(
        "MATCH (g:Goal {id: $gid}) SET " + ", ".join(set_clauses),
        {"gid": goal_id, "ts": datetime.now().isoformat(), "outcome": outcome}
    )