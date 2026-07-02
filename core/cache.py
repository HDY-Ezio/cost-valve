"""
AI Cost Optimizer - Cache System
精确缓存 + 语义缓存（embedding + 余弦相似度）
"""
import json
import hashlib
import logging
import uuid
import math
from typing import Optional, Dict, Any, List, Tuple

from config import get_config
from db.database import get_db

logger = logging.getLogger(__name__)


# ============================================================
# Cache Key 生成
# ============================================================

def make_cache_key(model: str, messages: List[Dict], temperature: Optional[float] = None,
                   max_tokens: Optional[int] = None) -> str:
    """生成精确缓存 key"""
    # 标准化：去掉空白差异
    canonical = json.dumps({
        "model": model,
        "messages": [{"role": m.get("role", ""), "content": m.get("content", "")} for m in messages],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ============================================================
# 简易 Embedding（Mock 模式）
# ============================================================

def _mock_embedding(text: str, dim: int = 1536) -> List[float]:
    """
    Mock embedding：基于文本 hash 生成伪向量
    真实生产环境应调用 OpenAI text-embedding-3-small 等模型
    """
    h = hashlib.sha512(text.encode("utf-8")).digest()
    # 扩展到 dim 个 float
    vec = []
    for i in range(dim):
        byte_idx = i % len(h)
        val = (h[byte_idx] + i * 7) % 256
        vec.append((val / 128.0) - 1.0)  # 归一化到 [-1, 1]
    # L2 归一化
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


async def compute_embedding(text: str) -> List[float]:
    """
    计算文本 embedding
    Mock 模式下使用伪向量，生产环境应接入真实 embedding API
    """
    cfg = get_config()
    # 如果有配置真实 embedding API key，可在此调用
    # 目前用 mock 实现，保证语义相近的文本得到相近的向量
    return _mock_embedding(text, cfg.embedding_dim)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算余弦相似度"""
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ============================================================
# 精确缓存
# ============================================================

async def get_exact_cache(model: str, messages: List[Dict],
                          temperature: Optional[float] = None,
                          max_tokens: Optional[int] = None) -> Optional[Dict]:
    """查询精确缓存"""
    try:
        cfg = get_config()
        if not cfg.cache_enabled:
            return None

        cache_key = make_cache_key(model, messages, temperature, max_tokens)
        db = get_db()
        result = db.get_exact_cache(cache_key)
        if result:
            logger.info(f"Exact cache hit: {cache_key[:12]}...")
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
        logger.error(f"get_exact_cache error: {e}")
        return None


async def set_exact_cache(cache_key: str, response: Dict, provider: str, model: str,
                          input_tokens: int, output_tokens: int):
    """写入精确缓存"""
    try:
        cfg = get_config()
        if not cfg.cache_enabled:
            return
        db = get_db()
        db.set_exact_cache(cache_key, response, provider, model, input_tokens, output_tokens, cfg.exact_cache_ttl)
    except Exception as e:
        logger.error(f"set_exact_cache error: {e}")


# ============================================================
# 语义缓存
# ============================================================

def _extract_query_text(messages: List[Dict]) -> str:
    """从消息列表中提取查询文本（用于 embedding）"""
    # 取最后一条用户消息作为查询主体
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")
    # fallback：拼接所有消息
    return " ".join(m.get("content", "") for m in messages)


async def get_semantic_cache(model: str, messages: List[Dict],
                             threshold: Optional[float] = None) -> Optional[Dict]:
    """
    语义缓存查询
    用 embedding + 余弦相似度匹配语义相似的请求
    """
    try:
        cfg = get_config()
        if not cfg.cache_enabled:
            return None

        threshold = threshold or cfg.semantic_threshold
        query_text = _extract_query_text(messages)
        if not query_text.strip():
            return None

        # 计算查询 embedding
        query_emb = await compute_embedding(query_text)

        # 获取所有候选缓存
        db = get_db()
        candidates = db.get_semantic_cache_candidates()
        if not candidates:
            return None

        # 找最相似的
        best_score = 0.0
        best_candidate = None
        for c in candidates:
            # 模型不同则跳过
            if c.get("model", "") != model and c.get("model", ""):
                continue
            score = cosine_similarity(query_emb, c["embedding"])
            if score > best_score:
                best_score = score
                best_candidate = c

        if best_candidate and best_score >= threshold:
            logger.info(f"Semantic cache hit: score={best_score:.4f}, key={best_candidate['cache_key'][:12]}...")
            db.update_semantic_cache_hit(best_candidate["cache_id"])
            return {
                "response": best_candidate["response"],
                "provider": best_candidate.get("provider", ""),
                "model": best_candidate.get("model", ""),
                "input_tokens": best_candidate.get("input_tokens", 0),
                "output_tokens": best_candidate.get("output_tokens", 0),
                "cache_type": "semantic",
                "similarity": round(best_score, 4),
            }

        return None
    except Exception as e:
        logger.error(f"get_semantic_cache error: {e}")
        return None


async def set_semantic_cache(model: str, messages: List[Dict], response: Dict,
                             provider: str, input_tokens: int, output_tokens: int):
    """写入语义缓存"""
    try:
        cfg = get_config()
        if not cfg.cache_enabled:
            return

        query_text = _extract_query_text(messages)
        if not query_text.strip():
            return

        embedding = await compute_embedding(query_text)
        cache_key = make_cache_key(model, messages)
        cache_id = uuid.uuid4().hex[:16]

        db = get_db()
        db.set_semantic_cache(cache_id, cache_key, embedding, response, provider, model,
                              input_tokens, output_tokens, cfg.semantic_cache_ttl)
    except Exception as e:
        logger.error(f"set_semantic_cache error: {e}")
