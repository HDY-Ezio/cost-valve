"""
节能阀 Cost Valve - 精确缓存系统
AI API 成本优化中间件 - 开源版

完全相同的请求直接返回缓存，省 100% token 费
"""
import json
import hashlib
import logging
from typing import Optional, Dict, Any, List

from config import get_config
from db.database import get_db

logger = logging.getLogger(__name__)


# ============================================================
# Cache Key 生成
# ============================================================

def make_cache_key(model: str, messages: List[Dict], temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None) -> str:
    """生成精确缓存 key
    
    对 model + messages + temperature + max_tokens 做 SHA256 哈希
    标准化处理：排序 keys、去掉空白差异，确保语义相同的请求生成相同的 key
    """
    canonical = json.dumps({
        "model": model,
        "messages": [{"role": m.get("role", ""), "content": m.get("content", "")} for m in messages],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ============================================================
# 精确缓存
# ============================================================

async def get_exact_cache(model: str, messages: List[Dict],
                          temperature: Optional[float] = None,
                          max_tokens: Optional[int] = None) -> Optional[Dict]:
    """查询精确缓存
    
    Args:
        model: 模型名称
        messages: 消息列表
        temperature: 温度参数
        max_tokens: 最大 token 数
    
    Returns:
        缓存命中返回响应 dict，未命中返回 None
    """
    try:
        cfg = get_config()
        if not cfg.cache_enabled:
            return None

        cache_key = make_cache_key(model, messages, temperature, max_tokens)
        db = get_db()
        result = db.get_exact_cache(cache_key)
        if result:
            logger.info(f"精确缓存命中: {cache_key[:12]}...")
            return {
                "response": result["response"],
                "provider": result["provider"],
                "model": result["model"],
                "input_tokens": result["input_tokens"],
                "output_tokens": result["output_tokens"],
                "cache_type": "exact",
            }
        return None
    except Exception as e:
        logger.error(f"精确缓存查询失败: {e}")
        return None


async def set_exact_cache(cache_key: str, response: Dict, provider: str, model: str,
                          input_tokens: int, output_tokens: int):
    """写入精确缓存
    
    Args:
        cache_key: 缓存 key
        response: 响应内容
        provider: 供应商名称
        model: 模型名称
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
    """
    try:
        cfg = get_config()
        if not cfg.cache_enabled:
            return
        db = get_db()
        db.set_exact_cache(cache_key, response, provider, model, 
                          input_tokens, output_tokens, cfg.exact_cache_ttl)
    except Exception as e:
        logger.error(f"精确缓存写入失败: {e}")
