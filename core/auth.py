"""
AI Cost Optimizer - API Key Authentication
"""
import hashlib
import logging
import uuid
from typing import Optional, Dict

from db.database import get_db

logger = logging.getLogger(__name__)


def hash_api_key(key: str) -> str:
    """对 API Key 做 SHA256 哈希"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    """生成一个新的 API Key"""
    return f"aco-{uuid.uuid4().hex}"


def authenticate(key: str) -> Optional[Dict]:
    """
    认证 API Key
    返回 key 信息 dict，失败返回 None
    """
    try:
        key_hash = hash_api_key(key)
        db = get_db()
        return db.get_api_key(key_hash)
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return None


def create_key(name: str = "", monthly_quota: int = 1000,
               monthly_budget: float = 100.0, contact: str = "",
               raw_key: str = None) -> Dict:
    """
    创建新 API Key
    返回 {key_id, api_key, name, ...}
    """
    try:
        key_id = uuid.uuid4().hex[:16]
        if raw_key is None:
            raw_key = generate_api_key()
        key_hash = hash_api_key(raw_key)

        db = get_db()
        success = db.create_api_key(key_id, key_hash, name, monthly_quota,
                                    monthly_budget, contact=contact, raw_key=raw_key)
        if not success:
            raise Exception("Failed to create API key (may already exist)")

        return {
            "key_id": key_id,
            "api_key": raw_key,
            "name": name,
            "monthly_quota": monthly_quota,
            "monthly_budget": monthly_budget,
        }
    except Exception as e:
        logger.error(f"create_key error: {e}")
        raise
