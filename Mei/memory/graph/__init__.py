"""
Kùzu Graph Memory — single import surface.

Usage:
    from Mei.memory.graph import write_episode, find_matching_goal, ...

Bootstraps the DB (schema + vector index) on first import.
"""

from .connection import KuzuConnection, get_kuzu_connection
from .schema import apply_schema, create_vector_index
from .embedder import embed
from .episodic import write_episode, load_episode
from .working import (create_session, close_session,
                      get_recent_goals, get_context_for_planner)
from .semantic import (save_entity, get_entity, search_entities,
                       cache_element, get_cached_element,
                       record_element_hit, record_element_miss,
                       upsert_app, get_app, search_apps)
from .preference import (set_preference, get_preference,
                         get_preferences_by_category,
                         get_preferences_for_prompt)
from .procedural import find_matching_goal, get_procedure


_bootstrapped = False

def init_graph():
    """Must be called explicitly during app startup, not at import time."""
    global _bootstrapped
    if _bootstrapped:
        return
    try:
        conn = get_kuzu_connection()
        apply_schema(conn)
        create_vector_index(conn)
        _bootstrapped = True
    except Exception as e:
        print(f"[Graph Memory] Bootstrap failed: {e}")

__all__ = [
    'init_graph',
    # Connection
    'get_kuzu_connection',
    # Embedder
    'embed',
    # Episodic
    'write_episode', 'load_episode',
    # Working / Session
    'create_session', 'close_session',
    'get_recent_goals', 'get_context_for_planner',
    # Semantic
    'save_entity', 'get_entity', 'search_entities',
    'cache_element', 'get_cached_element',
    'record_element_hit', 'record_element_miss',
    'upsert_app', 'get_app', 'search_apps',
    # Preference
    'set_preference', 'get_preference',
    'get_preferences_by_category', 'get_preferences_for_prompt',
    # Procedural
    'find_matching_goal', 'get_procedure',
]
