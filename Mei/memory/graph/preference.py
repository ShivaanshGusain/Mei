import json
import hashlib
from datetime import datetime
from typing import Any, Dict

from .connection import get_kuzu_connection


def set_preference(key: str, value: Any, category: str = 'general', is_explicit: bool = False, confidence: float = 0.5) -> None:
    """
    Sets a user preference in the Kùzu graph database.
    """
    try:
        conn = get_kuzu_connection()
        
        pref_id = f"pref_{hashlib.md5(key.encode()).hexdigest()[:12]}"
        timestamp = datetime.now().isoformat()
        
        if isinstance(value, bool):
            val_type = 'bool'
            val_str = str(value)
        elif isinstance(value, int) and not isinstance(value, bool):
            val_type = 'int'
            val_str = str(value)
        elif isinstance(value, float):
            val_type = 'float'
            val_str = str(value)
        elif isinstance(value, (dict, list)):
            val_type = 'json'
            val_str = json.dumps(value)
        else:
            val_type = 'string'
            val_str = str(value)
            
        query = """
        MERGE (p:Preference {pref_key: $key})
        ON CREATE SET p.id = $id, p.pref_value = $val, p.value_type = $vt,
                      p.category = $cat, p.confidence = $conf, p.is_explicit = $expl,
                      p.learned_at = $ts
        ON MATCH SET p.pref_value = $val, p.confidence = CASE WHEN $conf > p.confidence THEN $conf ELSE p.confidence END,
                     p.learned_at = $ts
        """
        params = {
            "key": key,
            "id": pref_id,
            "val": val_str,
            "vt": val_type,
            "cat": category,
            "conf": confidence,
            "expl": is_explicit,
            "ts": timestamp
        }
        conn.execute(query, params)
    except Exception as e:
        print(f"Error setting preference '{key}': {e}")


def _deserialize_value(val_str: str, val_type: str) -> Any:
    """Helper to deserialize string values back to python types."""
    if val_type == 'bool':
        return val_str.lower() == 'true'
    elif val_type == 'int':
        return int(val_str)
    elif val_type == 'float':
        return float(val_str)
    elif val_type == 'json':
        return json.loads(val_str)
    else:
        return val_str


def get_preference(key: str, default: Any = None, min_confidence: float = 0.0) -> Any:
    """
    Retrieves a user preference from the Kùzu graph database.
    """
    try:
        conn = get_kuzu_connection()
        query = """
        MATCH (p:Preference {pref_key: $key})
        WHERE p.confidence >= $min_conf
        RETURN p.pref_value AS val, p.value_type AS vt
        """
        results = conn.execute(query, {"key": key, "min_conf": min_confidence})
        
        if not results:
            return default
            
        row = results[0]
        return _deserialize_value(row['val'], row['vt'])
    except Exception as e:
        print(f"Error getting preference '{key}': {e}")
        return default


def get_preferences_by_category(category: str, min_confidence: float = 0.0) -> Dict[str, Any]:
    """
    Retrieves all preferences for a specific category.
    """
    try:
        conn = get_kuzu_connection()
        query = """
        MATCH (p:Preference {category: $cat})
        WHERE p.confidence >= $min_conf
        RETURN p.pref_key AS key, p.pref_value AS val, p.value_type AS vt
        """
        results = conn.execute(query, {"cat": category, "min_conf": min_confidence})
        
        prefs = {}
        for row in results:
            prefs[row['key']] = _deserialize_value(row['val'], row['vt'])
        return prefs
    except Exception as e:
        print(f"Error getting preferences by category '{category}': {e}")
        return {}


def get_preferences_for_prompt() -> str:
    """
    Formats preferences with sufficient confidence into a human-readable string.
    """
    # TODO (Micro-Planner): Ensure 'context["graph_preferences"]' is injected
    # into the iterative evaluation prompt for each step, not just a
    # single-shot initialization prompt.
    try:
        conn = get_kuzu_connection()
        query = """
        MATCH (p:Preference)
        WHERE p.confidence >= 0.3
        RETURN p.pref_key AS key, p.pref_value AS val, p.value_type AS vt
        """
        results = conn.execute(query, {})
        
        if not results:
            return ""
            
        lines = ["User preferences:"]
        for row in results:
            val = _deserialize_value(row['val'], row['vt'])
            lines.append(f"- {row['key']}: {val}")
            
        return "\n".join(lines)
    except Exception as e:
        print(f"Error formatting preferences for prompt: {e}")
        return ""