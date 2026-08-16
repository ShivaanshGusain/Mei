import kuzu
import threading
from typing import Any, Optional
from ...core.config import get_config

class KuzuConnection:
    def __init__(self, db_path : str):
        self._db= kuzu.Database(db_path)
        self._conn = kuzu.Connection(self._db)
        self._lock = threading.RLock()

    def execute(self, query: str, params: dict = None) -> list[dict]:
        with self._lock:
            result = self._conn.execute(query, params or {})
            rows = []
            col_names = result.get_column_names()
            while result.has_next():
                row_values = result.get_next()
                rows.append(dict(zip(col_names, row_values)))
            return rows

    def close(self):
        self._conn.close()

_instance : Optional[KuzuConnection] = None
_init_lock = threading.Lock()

def get_kuzu_connection() -> KuzuConnection:
    global _instance
    if _instance is None:
        with _init_lock:
            if _instance is None:
                path = get_config().kuzu.database_path
                _instance = KuzuConnection(path)
    return _instance

