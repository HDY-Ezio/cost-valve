"""
节能阀 Cost Valve - SQLite 数据库管理
AI API 成本优化中间件 - 开源版
"""
import os
import json
import time
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))


class Database:
    """SQLite 数据库管理器"""

    def __init__(self, db_path: str = "./data/cost_valve.db"):
        self.db_path = db_path
        self._ensure_dir()
        self._init_db()

    def _ensure_dir(self):
        dir_path = os.path.dirname(self.db_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        """初始化数据库表"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()

            # 精确缓存表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS exact_cache (
                    cache_key TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    hit_count INTEGER DEFAULT 0
                )
            """)

            # 用量记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usage_records (
                    record_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    cache_type TEXT DEFAULT 'none',
                    tokens_saved INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            # 索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_records(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exact_cache_expires ON exact_cache(expires_at)")

            conn.commit()
            conn.close()
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    # ============================================================
    # 精确缓存
    # ============================================================

    def get_exact_cache(self, cache_key: str) -> Optional[Dict]:
        """查询精确缓存"""
        try:
            conn = self._get_conn()
            now = time.time()
            row = conn.execute(
                "SELECT * FROM exact_cache WHERE cache_key = ? AND expires_at > ?",
                (cache_key, now)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE exact_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
                    (cache_key,)
                )
                conn.commit()
                result = dict(row)
                result["response"] = json.loads(result["response_json"])
                conn.close()
                return result
            conn.close()
            return None
        except Exception as e:
            logger.error(f"get_exact_cache error: {e}")
            return None

    def set_exact_cache(self, cache_key: str, response: Dict, provider: str, model: str,
                        input_tokens: int, output_tokens: int, ttl: int = 3600):
        """写入精确缓存"""
        try:
            conn = self._get_conn()
            now = time.time()
            conn.execute(
                "INSERT OR REPLACE INTO exact_cache "
                "(cache_key, response_json, provider, model, input_tokens, output_tokens, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cache_key, json.dumps(response, ensure_ascii=False), provider, model,
                 input_tokens, output_tokens, now, now + ttl)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"set_exact_cache error: {e}")

    # ============================================================
    # 用量记录
    # ============================================================

    def record_usage(self, record: Dict) -> bool:
        """记录一次调用"""
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO usage_records "
                "(record_id, request_id, provider, model, "
                "input_tokens, output_tokens, total_tokens, "
                "cache_type, tokens_saved, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["record_id"], record["request_id"],
                    record.get("provider", ""), record.get("model", ""),
                    record.get("input_tokens", 0), record.get("output_tokens", 0),
                    record.get("total_tokens", 0),
                    record.get("cache_type", "none"),
                    record.get("tokens_saved", 0),
                    record.get("created_at", datetime.now(CST).isoformat()),
                )
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"record_usage error: {e}")
            return False

    def get_usage_summary(self, days: int = 30) -> Dict:
        """获取用量统计摘要"""
        try:
            conn = self._get_conn()
            since = (datetime.now(CST) - timedelta(days=days)).isoformat()

            row = conn.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(CASE WHEN cache_type != 'none' THEN 1 ELSE 0 END), 0) as cache_hits,
                    COALESCE(SUM(CASE WHEN cache_type = 'exact' THEN 1 ELSE 0 END), 0) as exact_cache_hits,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(tokens_saved), 0) as total_tokens_saved
                FROM usage_records
                WHERE created_at >= ?
            """, (since,)).fetchone()

            # 今日调用
            today = datetime.now(CST).strftime("%Y-%m-%d")
            today_row = conn.execute("""
                SELECT COUNT(*) as calls_today
                FROM usage_records
                WHERE created_at >= ?
            """, (today,)).fetchone()

            conn.close()
            return {
                "total_calls": row["total_calls"] if row else 0,
                "cache_hits": row["cache_hits"] if row else 0,
                "exact_cache_hits": row["exact_cache_hits"] if row else 0,
                "total_tokens": row["total_tokens"] if row else 0,
                "total_tokens_saved": row["total_tokens_saved"] if row else 0,
                "cache_hit_rate": round(
                    (row["cache_hits"] / row["total_calls"] * 100)
                    if row and row["total_calls"] > 0 else 0, 1
                ),
                "calls_today": today_row["calls_today"] if today_row else 0,
            }
        except Exception as e:
            logger.error(f"get_usage_summary error: {e}")
            return {}

    def get_daily_usage(self, days: int = 7) -> List[Dict]:
        """获取每日用量趋势"""
        try:
            conn = self._get_conn()
            rows = conn.execute("""
                SELECT
                    DATE(created_at) as day,
                    COUNT(*) as calls,
                    COALESCE(SUM(total_tokens), 0) as tokens,
                    COALESCE(SUM(CASE WHEN cache_type != 'none' THEN 1 ELSE 0 END), 0) as cache_hits,
                    COALESCE(SUM(tokens_saved), 0) as tokens_saved
                FROM usage_records
                WHERE created_at >= ?
                GROUP BY DATE(created_at)
                ORDER BY day
            """, ((datetime.now(CST) - timedelta(days=days)).isoformat(),)).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_daily_usage error: {e}")
            return []

    def get_cache_stats(self) -> Dict:
        """获取缓存统计"""
        try:
            conn = self._get_conn()
            now = time.time()

            total_row = conn.execute("SELECT COUNT(*) as cnt FROM exact_cache WHERE expires_at > ?", (now,)).fetchone()
            hit_row = conn.execute("SELECT COALESCE(SUM(hit_count), 0) as total FROM exact_cache",).fetchone()

            conn.close()
            return {
                "active_entries": total_row["cnt"] if total_row else 0,
                "total_hits": hit_row["total"] if hit_row else 0,
            }
        except Exception as e:
            logger.error(f"get_cache_stats error: {e}")
            return {}

    # ============================================================
    # 缓存清理
    # ============================================================

    def cleanup_expired_cache(self):
        """清理过期缓存"""
        try:
            conn = self._get_conn()
            now = time.time()
            conn.execute("DELETE FROM exact_cache WHERE expires_at <= ?", (now,))
            conn.commit()
            conn.close()
            logger.info("Expired cache entries cleaned up")
        except Exception as e:
            logger.error(f"cleanup_expired_cache error: {e}")


# 全局数据库实例
_db: Optional[Database] = None


def get_db() -> Database:
    global _db
    if _db is None:
        from config import get_config
        cfg = get_config()
        _db = Database(cfg.db_path)
    return _db


def init_db(db_path: str = "./data/cost_valve.db") -> Database:
    global _db
    _db = Database(db_path)
    return _db
