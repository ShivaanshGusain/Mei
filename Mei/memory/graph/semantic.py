import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Any

from .connection import get_kuzu_connection

# ==========================================
# Entities
# ==========================================

def save_entity(entity: Any) -> str:
    """
    Saves an Entity dataclass instance to the graph as a flat node.
    """
    try:
        # Extract entity type as string
        entity_type_str = getattr(entity.entity_type, 'value', str(entity.entity_type)) if hasattr(entity, 'entity_type') else str(entity.entity_type)
        
        # Generate deterministic ID
        ent_id = f"ent_{hashlib.md5(f'{entity.canonical_name}:{entity_type_str}'.encode()).hexdigest()[:12]}"
        
        query = """
        MERGE (e:Entity {canonical_name: $canonical_name, entity_type: $entity_type})
        ON CREATE SET 
            e.id = $id,
            e.name = $name,
            e.resolution = $resolution,
            e.confidence = $confidence,
            e.source_app = $source_app,
            e.created_at = $created_at
        ON MATCH SET
            e.name = $name,
            e.resolution = $resolution,
            e.confidence = $confidence,
            e.source_app = $source_app
        RETURN e.id
        """
        
        params = {
            'id': ent_id,
            'canonical_name': getattr(entity, 'canonical_name', ''),
            'entity_type': entity_type_str,
            'name': getattr(entity, 'name', ''),
            'resolution': getattr(entity, 'value', ''),
            'confidence': 1.0,
            'source_app': getattr(entity, 'source_app', '') or '',
            'created_at': datetime.now().isoformat()
        }
        
        conn = get_kuzu_connection()
        conn.execute(query, params)
        return ent_id
    except Exception as e:
        print(f"Error saving entity: {e}")
        return ""

def get_entity(canonical_name: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves an entity by its canonical name.
    """
    try:
        query = """
        MATCH (e:Entity {canonical_name: $cn})
        RETURN e.*
        LIMIT 1
        """
        conn = get_kuzu_connection()
        result = conn.execute(query, {'cn': canonical_name})
        if result:
            return result[0]
        return None
    except Exception as e:
        print(f"Error getting entity: {e}")
        return None

def search_entities(query_str: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Searches entities by canonical_name or name.
    """
    try:
        query = """
        MATCH (e:Entity)
        WHERE e.canonical_name CONTAINS $q OR e.name CONTAINS $q
        RETURN e.*
        LIMIT $limit
        """
        conn = get_kuzu_connection()
        return conn.execute(query, {'q': query_str, 'limit': limit})
    except Exception as e:
        print(f"Error searching entities: {e}")
        return []

# ==========================================
# Element Cache
# ==========================================

def cache_element(
    element_query: str, 
    app_name: str, 
    bounding_box: Tuple[int, int, int, int], 
    source: str, 
    window_pattern: Optional[str] = None, 
    element_type: Optional[str] = None, 
    automation_id: Optional[str] = None, 
    element_name: Optional[str] = None
) -> None:
    """
    Caches an element with its bounding box and metadata.
    """
    try:
        x, y, w, h = bounding_box
        center_x = x + w // 2
        center_y = y + h // 2
        
        win_pat = window_pattern or ""
        # Deterministic ID based on query, app, and window pattern
        hash_input = f"{element_query}:{app_name}:{win_pat}"
        el_id = f"el_{hashlib.md5(hash_input.encode()).hexdigest()[:12]}"
        
        query = """
        MERGE (c:ElementCache {element_query: $eq, app_name: $an})
        ON CREATE SET
            c.id = $id,
            c.window_pattern = $wp,
            c.center_x = $cx,
            c.center_y = $cy,
            c.bounding_box_x = $bx,
            c.bounding_box_y = $by,
            c.bounding_box_w = $bw,
            c.bounding_box_h = $bh,
            c.source = $src,
            c.element_type = $et,
            c.automation_id = $aid,
            c.element_name = $en,
            c.hit_count = 1,
            c.confidence = 0.8,
            c.is_valid = true,
            c.last_hit = $now
        ON MATCH SET
            c.hit_count = c.hit_count + 1,
            c.confidence = CASE WHEN c.confidence + 0.05 > 1.0 THEN 1.0 ELSE c.confidence + 0.05 END,
            c.center_x = $cx,
            c.center_y = $cy,
            c.bounding_box_x = $bx,
            c.bounding_box_y = $by,
            c.bounding_box_w = $bw,
            c.bounding_box_h = $bh,
            c.last_hit = $now
        """
        
        params = {
            'eq': element_query,
            'an': app_name,
            'id': el_id,
            'wp': win_pat,
            'cx': center_x,
            'cy': center_y,
            'bx': x,
            'by': y,
            'bw': w,
            'bh': h,
            'src': source,
            'et': element_type or "",
            'aid': automation_id or "",
            'en': element_name or "",
            'now': datetime.now().isoformat()
        }
        
        conn = get_kuzu_connection()
        conn.execute(query, params)
    except Exception as e:
        print(f"Error caching element: {e}")

def get_cached_element(
    element_query: str, 
    app_name: str, 
    window_pattern: Optional[str] = None, 
    min_confidence: float = 0.5
) -> Optional[Dict[str, int]]:
    """
    Retrieves a cached element's bounding box dict.
    Returns: {'bounding_box_x': int, 'bounding_box_y': int, 'bounding_box_w': int, 'bounding_box_h': int}
    """
    try:
        query = """
        MATCH (c:ElementCache {element_query: $eq, app_name: $an})
        WHERE c.is_valid = true AND c.confidence >= $mc
        """
        params = {
            'eq': element_query,
            'an': app_name,
            'mc': min_confidence
        }
        
        if window_pattern:
            query += " AND c.window_pattern = $wp\n"
            params['wp'] = window_pattern
            
        query += "RETURN c.bounding_box_x, c.bounding_box_y, c.bounding_box_w, c.bounding_box_h LIMIT 1"
        
        conn = get_kuzu_connection()
        result = conn.execute(query, params)
        if result:
            row = result[0]
            # Must return exactly these keys
            return {
                'bounding_box_x': int(row.get('c.bounding_box_x', 0)),
                'bounding_box_y': int(row.get('c.bounding_box_y', 0)),
                'bounding_box_w': int(row.get('c.bounding_box_w', 0)),
                'bounding_box_h': int(row.get('c.bounding_box_h', 0))
            }
        return None
    except Exception as e:
        print(f"Error getting cached element: {e}")
        return None

def record_element_hit(element_query: str, app_name: str, window_pattern: Optional[str] = None) -> None:
    """
    Increases hit count and confidence for an element cache.
    """
    try:
        query = """
        MATCH (c:ElementCache {element_query: $eq, app_name: $an})
        """
        params = {
            'eq': element_query,
            'an': app_name,
            'now': datetime.now().isoformat()
        }
        
        if window_pattern:
            query += " WHERE c.window_pattern = $wp"
            params['wp'] = window_pattern
            
        query += """
        SET c.hit_count = c.hit_count + 1,
            c.confidence = CASE WHEN c.confidence + 0.05 > 1.0 THEN 1.0 ELSE c.confidence + 0.05 END,
            c.last_hit = $now
        """
        
        conn = get_kuzu_connection()
        conn.execute(query, params)
    except Exception as e:
        print(f"Error recording element hit: {e}")

def record_element_miss(element_query: str, app_name: str, window_pattern: Optional[str] = None, invalidate_threshold: float = 0.2) -> None:
    """
    Decreases confidence for an element cache and invalidates it if it drops below threshold.
    """
    try:
        params = {
            'eq': element_query,
            'an': app_name,
            'thresh': invalidate_threshold
        }
        
        # Step 1: Decrease confidence
        query1 = """
        MATCH (c:ElementCache {element_query: $eq, app_name: $an})
        """
        if window_pattern:
            query1 += " WHERE c.window_pattern = $wp"
            params['wp'] = window_pattern
            
        query1 += """
        SET c.confidence = CASE WHEN c.confidence - 0.15 < 0 THEN 0.0 ELSE c.confidence - 0.15 END
        """
        
        conn = get_kuzu_connection()
        conn.execute(query1, params)
        
        # Step 2: Invalidate if below threshold
        query2 = """
        MATCH (c:ElementCache {element_query: $eq, app_name: $an})
        WHERE c.confidence < $thresh
        """
        if window_pattern:
            query2 += " AND c.window_pattern = $wp"
            
        query2 += """
        SET c.is_valid = false
        """
        conn.execute(query2, params)
        
    except Exception as e:
        print(f"Error recording element miss: {e}")

# ==========================================
# App Library
# ==========================================

def upsert_app(app: Dict[str, Any]) -> None:
    """
    Inserts or updates an app in the AppLibrary.
    """
    try:
        exec_name = app.get('executable_name', '')
        app_id = f"app_{hashlib.md5(exec_name.encode()).hexdigest()[:12]}"
        
        query = """
        MERGE (a:AppLibrary {executable_name: $en})
        ON CREATE SET
            a.id = $id,
            a.display_name = $dn,
            a.executable_path = $ep,
            a.category = $cat,
            a.launch_method = $lm,
            a.is_available = $ia
        ON MATCH SET
            a.display_name = $dn,
            a.executable_path = $ep,
            a.category = $cat,
            a.launch_method = $lm,
            a.is_available = $ia
        """
        params = {
            'en': exec_name,
            'id': app_id,
            'dn': app.get('display_name', ''),
            'ep': app.get('executable_path', ''),
            'cat': app.get('category', ''),
            'lm': app.get('launch_method', ''),
            'ia': app.get('is_available', False)
        }
        
        conn = get_kuzu_connection()
        conn.execute(query, params)
    except Exception as e:
        print(f"Error upserting app: {e}")

def get_app(executable_name: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves an app by its executable name.
    """
    try:
        query = """
        MATCH (a:AppLibrary {executable_name: $en})
        RETURN a.*
        LIMIT 1
        """
        conn = get_kuzu_connection()
        result = conn.execute(query, {'en': executable_name})
        if result:
            return result[0]
        return None
    except Exception as e:
        print(f"Error getting app: {e}")
        return None

def search_apps(query_str: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Searches apps by display name or executable name.
    """
    try:
        query = """
        MATCH (a:AppLibrary)
        WHERE a.display_name CONTAINS $q OR a.executable_name CONTAINS $q
        RETURN a.*
        LIMIT $limit
        """
        conn = get_kuzu_connection()
        return conn.execute(query, {'q': query_str, 'limit': limit})
    except Exception as e:
        print(f"Error searching apps: {e}")
        return []