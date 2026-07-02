"""
AI Cost Optimizer - Usage Statistics
用量统计 + 成本可视化数据
"""
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from config import get_config
from db.database import get_db
from models import CacheType, now_iso

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))


def record_call(api_key_id: str, request_id: str, provider: str, model: str,
                input_tokens: int, output_tokens: int,
                original_cost: float, actual_cost: float, saved_cost: float,
                cache_type: CacheType = CacheType.NONE,
                was_offpeak: bool = False, priority: str = "immediate",
                was_delayed: bool = False, tokens_saved: int = 0,
                proxy_fee: float = 0.0,
                savings_json: Optional[Dict] = None) -> bool:
    """记录一次 API 调用"""
    try:
        db = get_db()
        record = {
            "record_id": uuid.uuid4().hex[:16],
            "api_key_id": api_key_id,
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "original_cost": original_cost,
            "actual_cost": actual_cost,
            "proxy_fee": proxy_fee,
            "saved_cost": saved_cost,
            "cache_type": cache_type.value,
            "was_offpeak": was_offpeak,
            "priority": priority,
            "was_delayed": was_delayed,
            "tokens_saved": tokens_saved,
            "savings_json": savings_json,
            "created_at": now_iso(),
        }
        success = db.record_usage(record)
        if success:
            # 更新 key 使用次数
            db.update_api_key_usage(api_key_id, increment=1)
        return success
    except Exception as e:
        logger.error(f"record_call error: {e}")
        return False


def get_dashboard(api_key_id: str) -> Dict:
    """
    获取完整的 Dashboard 数据
    """
    try:
        db = get_db()
        cfg = get_config()

        # 总量统计
        summary = db.get_usage_summary(api_key_id, days=30)

        # 每日趋势（7天）
        daily = db.get_daily_usage(api_key_id, days=7)

        # 预算状态
        from core.budget import check_budget
        _, budget_status = check_budget(api_key_id)

        # 计算总节省金额
        total_saved = summary.get("total_saved", 0.0)
        total_tokens_saved = summary.get("total_tokens_saved", 0)

        # 缓存命中率
        total_calls = summary.get("total_calls", 0)
        cache_hits = summary.get("cache_hits", 0)
        cache_hit_rate = (cache_hits / total_calls * 100) if total_calls > 0 else 0

        return {
            "overview": {
                "total_calls_30d": total_calls,
                "calls_today": summary.get("calls_today", 0),
                "total_tokens_30d": summary.get("total_tokens", 0),
                "total_cost_30d": summary.get("total_cost", 0.0),
                "total_saved_30d": round(total_saved, 4),
                "total_proxy_fee_30d": summary.get("total_proxy_fee", 0.0),
                "cache_hit_rate": round(cache_hit_rate, 1),
                "tokens_saved_by_optimization": total_tokens_saved,
            },
            "cache": {
                "total_cache_hits": cache_hits,
                "exact_cache_hits": summary.get("exact_cache_hits", 0),
                "semantic_cache_hits": summary.get("semantic_cache_hits", 0),
                "cache_hit_rate": round(cache_hit_rate, 1),
            },
            "budget": budget_status,
            "daily_trend": daily,
        }
    except Exception as e:
        logger.error(f"get_dashboard error: {e}")
        return {"error": str(e)}
