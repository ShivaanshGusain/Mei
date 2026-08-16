"""
Procedural memory module.

Provides HNSW vector search for finding matching past goals and retrieving
their action chains for direct execution (LLM bypass).
"""

from typing import Optional, List, Dict, Any
from .connection import get_kuzu_connection
from .embedder import embed

def find_matching_goal(raw_command: str, threshold: float) -> Optional[Dict[str, Any]]:
    """
    HNSW vector search on Goal nodes.
    Returns the best match above threshold or None.
    
    Return shape:
    {'id': str, 'raw_command': str, 'action': str, 'target': str, 'confidence': float}
    """
    try:
        embedding = embed(raw_command)
        
        # If embedding failed (zero vector), skip search
        if all(v == 0.0 for v in embedding[:10]):
            return None
        
        conn = get_kuzu_connection()
        rows = conn.execute("""
            CALL QUERY_VECTOR_INDEX('Goal', 'goal_hnsw', $emb, 5)
            YIELD node, distance
            WHERE (1.0 - distance) > $thresh
            RETURN node.id AS id, node.raw_command AS raw_command,
                   node.action AS action, node.target AS target,
                   (1.0 - distance) AS confidence
            ORDER BY confidence DESC LIMIT 1
        """, {"emb": embedding, "thresh": threshold})
        
        return rows[0] if rows else None
    except Exception as e:
        print(f"Error in find_matching_goal (index might not exist yet): {e}")
        return None

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
                   a.duration_ms AS duration_ms
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
                
        return procedure
    except Exception as e:
        print(f"Error in get_procedure: {e}")
        return []