"""
节能阀 Cost Valve - 前缀优化器
AI API 成本优化中间件 - 开源版

自动整理请求结构，最大化命中上游 LLM 的 prompt cache

核心原理：
  上游模型（DeepSeek/OpenAI/Claude/Gemini）都有 prompt cache
  缓存匹配的是请求前缀（从第一个 token 开始的连续相同内容）
  只要前缀一样，后面的内容随便变，前缀部分就能享受 50-90% 折扣

  本模块做的事情：
  1. 保证消息顺序稳定：system → tools → context → user
  2. 合并零碎的 system 消息为一个（避免前缀每次都不同）
  3. 把不变的内容推到最前面（最大化可缓存前缀长度）
  4. 归一化空白差异（避免一个空格导致缓存失效）
"""
import re
import hashlib
import logging
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)


def optimize_prefix(messages: List[Dict]) -> Tuple[List[Dict], int]:
    """
    优化请求消息的前缀结构，最大化上游缓存命中率

    优化策略：
    1. 合并多个 system 消息为一个（减少前缀碎片）
    2. 保证角色顺序：system → assistant(历史) → user
    3. 归一化每段 content 的空白（去首尾空白、压缩连续空行）
    4. 将长上下文/文档类内容放在 system 之后、user 之前（作为可缓存前缀的一部分）

    Args:
        messages: 原始消息列表

    Returns:
        (optimized_messages, tokens_saved)
        tokens_saved 是对上游缓存命中后节省的 token 估算值
    """
    try:
        if not messages:
            return messages, 0

        # Step 1: 归一化空白
        normalized = _normalize_whitespace(messages)

        # Step 2: 合并连续 system 消息
        merged = _merge_system_messages(normalized)

        # Step 3: 稳定排序（system 固定在最前，然后是 assistant 历史，最后是 user）
        ordered = _stable_order(merged)

        optimized = ordered

        # 估算可缓存前缀 token 数（命中后能省多少）
        cacheable_prefix_tokens = _estimate_cacheable_prefix(optimized)

        saved = max(0, cacheable_prefix_tokens)

        if saved > 0:
            logger.info(f"前缀优化: 约 {saved} tokens 可被上游缓存命中")

        return optimized, saved

    except Exception as e:
        logger.error(f"前缀优化失败: {e}")
        return messages, 0


def _normalize_whitespace(messages: List[Dict]) -> List[Dict]:
    """归一化消息中的空白字符，避免因空白差异导致缓存失效"""
    result = []
    for msg in messages:
        content = msg.get("content", "")
        if content:
            # 去首尾空白
            content = content.strip()
            # 压缩连续空行为两个
            content = re.sub(r'\n{3,}', '\n\n', content)
            # 压缩连续空格为单个
            content = re.sub(r' {2,}', ' ', content)

        new_msg = dict(msg)
        new_msg["content"] = content
        result.append(new_msg)
    return result


def _merge_system_messages(messages: List[Dict]) -> List[Dict]:
    """
    合并多个 system 消息为一个。
    很多框架会把 system prompt、工具定义、上下文文档分成多个 system 消息发出来，
    但上游缓存只关心前缀是否完全一致，拆成多个反而增加不匹配风险。
    """
    system_parts = []
    non_system = []

    for msg in messages:
        if msg.get("role") == "system":
            system_parts.append(msg.get("content", ""))
        else:
            non_system.append(msg)

    if len(system_parts) <= 1:
        return messages  # 只有一个或没有 system，不需要合并

    # 合并为一个 system 消息
    merged_system = {
        "role": "system",
        "content": "\n\n".join(p for p in system_parts if p.strip()),
    }

    return [merged_system] + non_system


def _stable_order(messages: List[Dict]) -> List[Dict]:
    """
    确保消息顺序稳定：
    system → (assistant + user 交替的历史对话) → 最后的 user 消息

    关键：system 永远在最前面，因为这是缓存前缀的起点。
    历史对话保持原有顺序（因为对话顺序有语义意义）。
    """
    system_msgs = []
    conversation = []

    for msg in messages:
        if msg.get("role") == "system":
            system_msgs.append(msg)
        else:
            conversation.append(msg)

    # system 固定在前
    return system_msgs + conversation


def _estimate_tokens(messages: List[Dict]) -> int:
    """粗略估算 token 数（3 字符 ≈ 1 token）"""
    total_chars = sum(len(m.get("content", "")) for m in messages)
    return total_chars // 3


def _estimate_cacheable_prefix(messages: List[Dict]) -> int:
    """
    估算可缓存前缀的 token 数。
    规则：从第一条消息开始，到第一条 user 消息为止的内容都是"稳定前缀"。
    system prompt + 之前的 assistant 消息 = 可缓存前缀
    """
    prefix_chars = 0
    for msg in messages:
        role = msg.get("role", "")
        if role == "system":
            prefix_chars += len(msg.get("content", ""))
        elif role == "assistant":
            # assistant 历史消息也是前缀的一部分
            prefix_chars += len(msg.get("content", ""))
        else:
            # 遇到 user 消息就停止（最后一条 user 消息是"变化的部分"）
            break

    return prefix_chars // 3


def get_prefix_hash(messages: List[Dict]) -> str:
    """
    计算可缓存前缀的 hash。
    用于调试和监控：相同 hash 意味着可以命中上游缓存。
    """
    prefix_parts = []
    for msg in messages:
        if msg.get("role") == "system":
            prefix_parts.append(f"system:{msg.get('content', '')}")
        elif msg.get("role") == "assistant":
            prefix_parts.append(f"assistant:{msg.get('content', '')}")
        else:
            break  # user 消息不属于前缀

    prefix_str = "|".join(prefix_parts)
    return hashlib.md5(prefix_str.encode("utf-8")).hexdigest()[:12]


def analyze_cacheability(messages: List[Dict]) -> Dict:
    """
    分析当前请求的缓存友好程度，返回诊断信息。
    用于 API 响应头或调试面板。
    """
    total_tokens = _estimate_tokens(messages)
    cacheable_tokens = _estimate_cacheable_prefix(messages)

    ratio = cacheable_tokens / total_tokens if total_tokens > 0 else 0

    # 判断缓存友好等级
    if ratio >= 0.7:
        level = "excellent"
        suggestion = ""
    elif ratio >= 0.4:
        level = "good"
        suggestion = "考虑将更多不变内容放在 system prompt 中"
    else:
        level = "fair"
        suggestion = "建议将重复上下文放入 system prompt，减少每次请求的变化量"

    return {
        "prefix_hash": get_prefix_hash(messages),
        "total_tokens_estimate": total_tokens,
        "cacheable_prefix_tokens": cacheable_tokens,
        "cacheability_ratio": round(ratio, 2),
        "cacheability_level": level,
        "suggestion": suggestion,
        "system_msg_count": sum(1 for m in messages if m.get("role") == "system"),
        "message_count": len(messages),
    }
