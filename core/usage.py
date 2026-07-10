"""
节能阀 Cost Valve - 用量统计
AI API 成本优化中间件 - 开源版

基础用量统计和缓存命中统计
"""
import uuid
import logging
from typing import Dict

from db.database import get_db
from models import CacheType, now_iso

logger = logging.getLogger(__name__)


def record_call(
    request_id: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_type: CacheType = CacheType.NONE,
    tokens_saved: int = 0,
):
    """
    记录一次 API 调用
    
    Args:
        request_id: 请求 ID
        provider: 供应商名称
        model: 模型名称
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        cache_type: 缓存类型 (none/exact)
        tokens_saved: 通过优化节省的 token 数
    """
    try:
        record_id = uuid.uuid4().hex[:16]
        total_tokens = input_tokens + output_tokens
        
        db = get_db()
        db.record_usage({
            "record_id": record_id,
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cache_type": cache_type.value,
            "tokens_saved": tokens_saved,
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.error(f"记录用量失败: {e}")


def get_usage_dashboard(days: int = 30) -> Dict:
    """
    获取用量看板数据
    
    Args:
        days: 统计天数
    
    Returns:
        用量统计 dict
    """
    try:
        db = get_db()
        summary = db.get_usage_summary(days=days)
        daily = db.get_daily_usage(days=days)
        cache_stats = db.get_cache_stats()
        
        return {
            "period": f"最近 {days} 天",
            "summary": summary,
            "daily_trend": daily,
            "cache_stats": cache_stats,
        }
    except Exception as e:
        logger.error(f"获取用量看板失败: {e}")
        return {"error": str(e)}
