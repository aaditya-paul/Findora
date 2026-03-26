import sqlite3
import json
import time
from typing import Optional, Any
from pathlib import Path
import logging

log = logging.getLogger(__name__)

class SqliteCache:
    def __init__(self, db_path: str = "data/cache.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    expires_at REAL
                )
            """)

    def set(self, key: str, value: Any, ttl_hours: float = 24.0):
        expires_at = time.time() + (ttl_hours * 3600)
        
        try:
            if hasattr(value, "model_dump_json"):
                value_str = value.model_dump_json()
            elif hasattr(value, "model_dump"):
                value_str = json.dumps(value.model_dump())
            elif isinstance(value, dict) or isinstance(value, list):
                value_str = json.dumps(value)
            else:
                value_str = str(value)
                
            with self.conn:
                self.conn.execute(
                    "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                    (key, value_str, expires_at)
                )
        except Exception as e:
            log.error(f"[CACHE] Error setting key {key}: {e}")

    def get(self, key: str) -> Optional[Any]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                value_str, expires_at = row
                if time.time() > expires_at:
                    self._delete(key)
                    return None
                try:
                    return json.loads(value_str)
                except json.JSONDecodeError:
                    return value_str
            return None
        except Exception as e:
            log.error(f"[CACHE] Error getting key {key}: {e}")
            return None

    def _delete(self, key: str):
        with self.conn:
            self.conn.execute("DELETE FROM cache WHERE key = ?", (key,))

    def is_fresh(self, key: str, ttl_hours: float = 0) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT expires_at FROM cache WHERE key = ?", (key,))
        row = cursor.fetchone()
        if not row:
            return False
        return time.time() < row[0]
