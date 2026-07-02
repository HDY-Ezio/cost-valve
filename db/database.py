"""
AI Cost Optimizer - SQLite Database Manager
异步 SQLite 数据库管理，支持用量记录、缓存、API Key 管理
"""
import os
import json
import time
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))


class Database:
    """SQLite 数据库管理器（线程安全，使用线程本地连接）"""

    def __init__(self, db_path: str = "./data/ai_cost_optimizer.db"):
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

            # API Keys 表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    key_hash TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    monthly_quota INTEGER DEFAULT 1000,
                    used_this_month INTEGER DEFAULT 0,
                    balance REAL DEFAULT 0.0,
                    monthly_budget REAL DEFAULT 100.0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT DEFAULT '',
                    reset_day INTEGER DEFAULT 1,
                    alert_threshold INTEGER DEFAULT 0,
                    reminder_sent INTEGER DEFAULT 0
                )
            """)

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

            # 语义缓存表（存 embedding 向量）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS semantic_cache (
                    cache_id TEXT PRIMARY KEY,
                    cache_key TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
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
                    api_key_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    original_cost REAL DEFAULT 0.0,
                    actual_cost REAL DEFAULT 0.0,
                    proxy_fee REAL DEFAULT 0.0,
                    saved_cost REAL DEFAULT 0.0,
                    cache_type TEXT DEFAULT 'none',
                    was_offpeak INTEGER DEFAULT 0,
                    priority TEXT DEFAULT 'immediate',
                    was_delayed INTEGER DEFAULT 0,
                    tokens_saved INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            # 异步调度队列表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    task_id TEXT PRIMARY KEY,
                    api_key_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    priority TEXT DEFAULT 'normal',
                    status TEXT DEFAULT 'pending',
                    scheduled_at TEXT DEFAULT '',
                    executed_at TEXT DEFAULT '',
                    completed_at TEXT DEFAULT '',
                    retry_count INTEGER DEFAULT 0,
                    response_json TEXT DEFAULT '',
                    error TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)

            # 预算告警记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS budget_alerts (
                    alert_id TEXT PRIMARY KEY,
                    api_key_id TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # 兼容迁移：给旧表加新字段
            try:
                cursor.execute("ALTER TABLE api_keys ADD COLUMN alert_threshold INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE api_keys ADD COLUMN reminder_sent INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE api_keys ADD COLUMN contact TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE api_keys ADD COLUMN raw_key TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE usage_records ADD COLUMN savings_json TEXT DEFAULT '{}'")
            except sqlite3.OperationalError:
                pass

            # 索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_api_key ON usage_records(api_key_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_records(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exact_cache_expires ON exact_cache(expires_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_semantic_cache_expires ON semantic_cache(expires_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON scheduled_tasks(status)")

            conn.commit()
            conn.close()
            logger.info(f"Database initialized at {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    # ============================================================
    # API Key 管理
    # ============================================================

    def create_api_key(self, key_id: str, key_hash: str, name: str = "",
                       monthly_quota: int = 1000, monthly_budget: float = 100.0,
                       contact: str = "", raw_key: str = "") -> bool:
        try:
            conn = self._get_conn()
            now = datetime.now(CST).isoformat()
            conn.execute(
                "INSERT INTO api_keys (key_id, key_hash, name, monthly_quota, monthly_budget, created_at, contact, raw_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (key_id, key_hash, name, monthly_quota, monthly_budget, now, contact, raw_key)
            )
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.error(f"create_api_key error: {e}")
            return False

    def get_api_key(self, key_hash: str) -> Optional[Dict]:
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = ? AND is_active = 1",
                (key_hash,)
            ).fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_api_key error: {e}")
            return None

    def update_api_key_usage(self, key_id: str, increment: int = 1):
        try:
            conn = self._get_conn()
            now = datetime.now(CST).isoformat()
            conn.execute(
                "UPDATE api_keys SET used_this_month = used_this_month + ?, last_used_at = ? WHERE key_id = ?",
                (increment, now, key_id)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"update_api_key_usage error: {e}")

    def reset_monthly_usage(self):
        """每月重置所有 key 的用量"""
        try:
            conn = self._get_conn()
            conn.execute("UPDATE api_keys SET used_this_month = 0")
            conn.commit()
            conn.close()
            logger.info("Monthly usage reset for all API keys")
        except Exception as e:
            logger.error(f"reset_monthly_usage error: {e}")

    def deduct_balance(self, key_id: str, amount: float) -> bool:
        """扣减余额"""
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE api_keys SET balance = balance - ? WHERE key_id = ? AND balance >= ?",
                (amount, key_id, amount)
            )
            changed = conn.totalchanges
            conn.commit()
            conn.close()
            return changed > 0
        except Exception as e:
            logger.error(f"deduct_balance error: {e}")
            return False

    def add_balance(self, key_id: str, amount: float) -> bool:
        """增加余额（充值）"""
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE api_keys SET balance = balance + ? WHERE key_id = ?",
                (amount, key_id)
            )
            changed = conn.totalchanges
            conn.commit()
            conn.close()
            return changed > 0
        except Exception as e:
            logger.error(f"add_balance error: {e}")
            return False

    def get_balance(self, key_id: str) -> float:
        """查询余额"""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT balance FROM api_keys WHERE key_id = ?", (key_id,)
            ).fetchone()
            conn.close()
            return row["balance"] if row else 0.0
        except Exception as e:
            logger.error(f"get_balance error: {e}")
            return 0.0

    def set_alert_threshold(self, key_id: str, threshold: int) -> bool:
        """设置剩余次数提醒阈值"""
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE api_keys SET alert_threshold = ?, reminder_sent = 0 WHERE key_id = ?",
                (threshold, key_id)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"set_alert_threshold error: {e}")
            return False

    def check_and_mark_reminder(self, key_id: str) -> Optional[Dict]:
        """检查是否需要发送提醒，如果需要则标记并返回 key 信息，否则返回 None"""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT key_id, name, used_this_month, monthly_quota, balance, alert_threshold, reminder_sent "
                "FROM api_keys WHERE key_id = ? AND alert_threshold > 0 AND reminder_sent = 0",
                (key_id,)
            ).fetchone()
            if not row:
                conn.close()
                return None
            info = dict(row)
            remaining_free = max(0, info["monthly_quota"] - info["used_this_month"])
            if remaining_free <= info["alert_threshold"]:
                # 标记已提醒，避免重复
                conn.execute(
                    "UPDATE api_keys SET reminder_sent = 1 WHERE key_id = ?", (key_id,)
                )
                conn.commit()
                conn.close()
                info["remaining_free"] = remaining_free
                return info
            conn.close()
            return None
        except Exception as e:
            logger.error(f"check_and_mark_reminder error: {e}")
            return None

    # ============================================================
    # 联系方式 & 原始 Key
    # ============================================================

    def find_key_by_contact(self, contact: str) -> Optional[Dict]:
        """根据邮箱/联系方式查找 API Key"""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT * FROM api_keys WHERE contact = ? AND is_active = 1",
                (contact,)
            ).fetchone()
            conn.close()
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error(f"find_key_by_contact error: {e}")
            return None

    def update_contact(self, key_id: str, contact: str) -> bool:
        """更新 API Key 的联系方式（邮箱）"""
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE api_keys SET contact = ? WHERE key_id = ?",
                (contact, key_id)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"update_contact error: {e}")
            return False

    def update_raw_key(self, key_id: str, raw_key: str) -> bool:
        """更新 API Key 的原始密钥（用于邮件找回）"""
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE api_keys SET raw_key = ? WHERE key_id = ?",
                (raw_key, key_id)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"update_raw_key error: {e}")
            return False

    # ============================================================
    # 精确缓存
    # ============================================================

    def get_exact_cache(self, cache_key: str) -> Optional[Dict]:
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
    # 语义缓存
    # ============================================================

    def get_semantic_cache_candidates(self) -> List[Dict]:
        """获取所有未过期的语义缓存记录（用于相似度匹配）"""
        try:
            conn = self._get_conn()
            now = time.time()
            rows = conn.execute(
                "SELECT * FROM semantic_cache WHERE expires_at > ?",
                (now,)
            ).fetchall()
            conn.close()
            results = []
            for row in rows:
                d = dict(row)
                d["embedding"] = json.loads(d["embedding_json"])
                d["response"] = json.loads(d["response_json"])
                results.append(d)
            return results
        except Exception as e:
            logger.error(f"get_semantic_cache_candidates error: {e}")
            return []

    def set_semantic_cache(self, cache_id: str, cache_key: str, embedding: List[float],
                           response: Dict, provider: str, model: str,
                           input_tokens: int, output_tokens: int, ttl: int = 86400):
        try:
            conn = self._get_conn()
            now = time.time()
            conn.execute(
                "INSERT OR REPLACE INTO semantic_cache "
                "(cache_id, cache_key, embedding_json, response_json, provider, model, "
                "input_tokens, output_tokens, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cache_id, cache_key, json.dumps(embedding), json.dumps(response, ensure_ascii=False),
                 provider, model, input_tokens, output_tokens, now, now + ttl)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"set_semantic_cache error: {e}")

    def update_semantic_cache_hit(self, cache_id: str):
        try:
            conn = self._get_conn()
            conn.execute(
                "UPDATE semantic_cache SET hit_count = hit_count + 1 WHERE cache_id = ?",
                (cache_id,)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"update_semantic_cache_hit error: {e}")

    # ============================================================
    # 用量记录
    # ============================================================

    def record_usage(self, record: Dict) -> bool:
        try:
            conn = self._get_conn()
            savings_json_str = json.dumps(record.get("savings_json", {}))
            conn.execute(
                "INSERT INTO usage_records "
                "(record_id, api_key_id, request_id, provider, model, "
                "input_tokens, output_tokens, total_tokens, "
                "original_cost, actual_cost, proxy_fee, saved_cost, "
                "cache_type, was_offpeak, priority, was_delayed, tokens_saved, savings_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["record_id"], record["api_key_id"], record["request_id"],
                    record.get("provider", ""), record.get("model", ""),
                    record.get("input_tokens", 0), record.get("output_tokens", 0),
                    record.get("total_tokens", 0),
                    record.get("original_cost", 0.0), record.get("actual_cost", 0.0),
                    record.get("proxy_fee", 0.0), record.get("saved_cost", 0.0),
                    record.get("cache_type", "none"), 1 if record.get("was_offpeak") else 0,
                    record.get("priority", "immediate"),
                    1 if record.get("was_delayed") else 0,
                    record.get("tokens_saved", 0),
                    savings_json_str,
                    record.get("created_at", datetime.now(CST).isoformat()),
                )
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"record_usage error: {e}")
            return False

    def get_usage_summary(self, api_key_id: str, days: int = 30) -> Dict:
        """获取用量统计"""
        try:
            conn = self._get_conn()
            since = (datetime.now(CST) - timedelta(days=days)).isoformat()

            # 总览
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    COALESCE(SUM(CASE WHEN cache_type != 'none' THEN 1 ELSE 0 END), 0) as cache_hits,
                    COALESCE(SUM(CASE WHEN cache_type = 'exact' THEN 1 ELSE 0 END), 0) as exact_cache_hits,
                    COALESCE(SUM(CASE WHEN cache_type = 'semantic' THEN 1 ELSE 0 END), 0) as semantic_cache_hits,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(actual_cost), 0) as total_cost,
                    COALESCE(SUM(saved_cost), 0) as total_saved,
                    COALESCE(SUM(proxy_fee), 0) as total_proxy_fee,
                    COALESCE(SUM(tokens_saved), 0) as total_tokens_saved
                FROM usage_records
                WHERE api_key_id = ? AND created_at >= ?
            """, (api_key_id, since)).fetchone()

            # 今日调用
            today = datetime.now(CST).strftime("%Y-%m-%d")
            today_row = conn.execute("""
                SELECT COUNT(*) as calls_today
                FROM usage_records
                WHERE api_key_id = ? AND created_at >= ?
            """, (api_key_id, today)).fetchone()

            conn.close()
            return {
                "total_calls": row["total_calls"] if row else 0,
                "cache_hits": row["cache_hits"] if row else 0,
                "exact_cache_hits": row["exact_cache_hits"] if row else 0,
                "semantic_cache_hits": row["semantic_cache_hits"] if row else 0,
                "total_tokens": row["total_tokens"] if row else 0,
                "total_cost": round(row["total_cost"], 4) if row else 0.0,
                "total_saved": round(row["total_saved"], 4) if row else 0.0,
                "total_proxy_fee": round(row["total_proxy_fee"], 4) if row else 0.0,
                "total_tokens_saved": row["total_tokens_saved"] if row else 0,
                "calls_today": today_row["calls_today"] if today_row else 0,
            }
        except Exception as e:
            logger.error(f"get_usage_summary error: {e}")
            return {}

    def get_daily_usage(self, api_key_id: str, days: int = 7) -> List[Dict]:
        """获取每日用量趋势"""
        try:
            conn = self._get_conn()
            rows = conn.execute("""
                SELECT
                    DATE(created_at) as day,
                    COUNT(*) as calls,
                    COALESCE(SUM(total_tokens), 0) as tokens,
                    COALESCE(SUM(actual_cost), 0) as cost,
                    COALESCE(SUM(saved_cost), 0) as saved
                FROM usage_records
                WHERE api_key_id = ? AND created_at >= ?
                GROUP BY DATE(created_at)
                ORDER BY day
            """, (api_key_id, (datetime.now(CST) - timedelta(days=days)).isoformat())).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_daily_usage error: {e}")
            return []

    # ============================================================
    # 调度任务
    # ============================================================

    def create_task(self, task: Dict) -> bool:
        try:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO scheduled_tasks "
                "(task_id, api_key_id, request_json, priority, status, scheduled_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task["task_id"], task["api_key_id"], task["request_json"],
                 task.get("priority", "normal"), task.get("status", "pending"),
                 task.get("scheduled_at", ""), task.get("created_at", datetime.now(CST).isoformat()))
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"create_task error: {e}")
            return False

    def get_pending_tasks(self, limit: int = 10) -> List[Dict]:
        try:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE status = 'pending' ORDER BY priority, created_at LIMIT ?",
                (limit,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_pending_tasks error: {e}")
            return []

    def update_task_status(self, task_id: str, status: str, response_json: str = "", error: str = ""):
        try:
            conn = self._get_conn()
            now = datetime.now(CST).isoformat()
            if status == "executing":
                conn.execute(
                    "UPDATE scheduled_tasks SET status = ?, executed_at = ? WHERE task_id = ?",
                    (status, now, task_id)
                )
            else:
                conn.execute(
                    "UPDATE scheduled_tasks SET status = ?, completed_at = ?, response_json = ?, error = ? WHERE task_id = ?",
                    (status, now, response_json, error, task_id)
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"update_task_status error: {e}")

    # ============================================================
    # 预算告警
    # ============================================================

    def record_budget_alert(self, api_key_id: str, alert_type: str, message: str):
        try:
            import uuid
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO budget_alerts (alert_id, api_key_id, alert_type, message, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:16], api_key_id, alert_type, message, datetime.now(CST).isoformat())
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"record_budget_alert error: {e}")

    # ============================================================
    # 缓存清理
    # ============================================================

    def cleanup_expired_cache(self):
        """清理过期缓存"""
        try:
            conn = self._get_conn()
            now = time.time()
            conn.execute("DELETE FROM exact_cache WHERE expires_at <= ?", (now,))
            conn.execute("DELETE FROM semantic_cache WHERE expires_at <= ?", (now,))
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


def init_db(db_path: str = "./data/ai_cost_optimizer.db") -> Database:
    global _db
    _db = Database(db_path)
    return _db
