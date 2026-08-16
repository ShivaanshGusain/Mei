from .connection import KuzuConnection, get_kuzu_connection
from .schema import apply_schema, create_vector_index
from .embedder import embed
from .episodic import write_episode, load_episode
from .working import create_session, close_session, get_recent_goals, get_context_for_planner
from .semantic import (save_entity, get_entity, search_entities,
                       cache_element, get_cached_element,
                       record_element_hit, record_element_miss,
                       upsert_app, get_app, search_apps)
from .preference import (set_preference, get_preference,
                         get_preferences_by_category, get_preferences_for_prompt)
from .procedural import find_matching_goal, get_procedure

def _bootstrap():
    """Called once on import. Creates schema + vector index if needed."""
    conn = get_kuzu_connection()
    apply_schema(conn)
    create_vector_index(conn)

_bootstrap()


__all__ = [
    'get_kuzu_connection',
    'embed', 'embed_batch',
    'write_episode', 'load_episode',
    'create_session', 'close_session', 'get_context_for_planner',
    'save_entity', 'get_entity', 'search_entities',
    'cache_element', 'get_cached_element',
    'record_element_hit', 'record_element_miss',
    'upsert_app', 'get_app',
    'set_preference', 'get_preference',
    'get_preferences_by_category', 'get_preferences_for_prompt',
    'find_matching_goal', 'get_procedure',
]
