"""
节能阀 Cost Valve - Prompt 瘦身优化器
AI API 成本优化中间件 - 开源版

转发前自动精简 prompt，减少 token 消耗
"""
import re
import logging
from typing import List, Dict, Tuple

from config import get_config

logger = logging.getLogger(__name__)


def optimize_messages(messages: List[Dict], enabled: bool = True) -> Tuple[List[Dict], int]:
    """
    优化消息列表，减少 token 消耗

    优化策略:
    1. 去除多余空白行
    2. 合并连续的相同 role 消息
    3. 截断超长 system prompt（保留核心指令）
    4. 去除无意义的分隔符
    5. 压缩重复的上下文内容

    Args:
        messages: 原始消息列表
        enabled: 是否启用优化

    Returns:
        (optimized_messages, tokens_saved)
    """
    try:
        cfg = get_config()
        if not enabled or not cfg.prompt_optimize_enabled:
            return messages, 0

        original_chars = sum(len(m.get("content", "")) for m in messages)
        optimized = []

        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "user")

            # 策略1: 去除多余空白
            content = _strip_excess_whitespace(content)

            # 策略2: 去除无意义分隔符
            content = _remove_useless_separators(content)

            # 策略3: 对 system prompt 做特殊处理（截断超长）
            if role == "system":
                content = _trim_system_prompt(content, cfg.prompt_max_tokens)

            # 策略4: 去重复内容（简单去重）
            content = _deduplicate_paragraphs(content)

            optimized.append({
                "role": role,
                "content": content,
                **({"name": msg["name"]} if msg.get("name") else {}),
            })

        # 策略5: 合并连续同 role 消息
        optimized = _merge_consecutive_same_role(optimized)

        optimized_chars = sum(len(m.get("content", "")) for m in optimized)
        # 粗略估算: 1 token ≈ 3 chars
        tokens_saved = max(0, (original_chars - optimized_chars) // 3)

        if tokens_saved > 0:
            logger.info(f"Prompt 瘦身: {original_chars} → {optimized_chars} 字符, 约节省 {tokens_saved} tokens")

        return optimized, tokens_saved
    except Exception as e:
        logger.error(f"Prompt 优化失败: {e}")
        return messages, 0


def _strip_excess_whitespace(text: str) -> str:
    """去除多余空白行和行首尾空格"""
    # 连续3个以上换行 → 2个换行
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 每行去首尾空格
    lines = [line.strip() for line in text.split('\n')]
    return '\n'.join(lines)


def _remove_useless_separators(text: str) -> str:
    """去除无意义的分隔符"""
    # 去除 ---, ***, === 等纯分隔符行（保留有上下文的）
    text = re.sub(r'\n[-=*]{3,}\n', '\n', text)
    # 去除连续的多个空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def _trim_system_prompt(text: str, max_tokens: int) -> str:
    """截断超长的 system prompt"""
    # 粗略: max_tokens * 3 chars
    max_chars = max_tokens * 3
    if len(text) <= max_chars:
        return text
    # 保留前 80% + 最后 10%（最后的指令通常更重要）
    keep_front = int(max_chars * 0.8)
    keep_back = int(max_chars * 0.1)
    return text[:keep_front] + "\n[...truncated...]\n" + text[-keep_back:]


def _deduplicate_paragraphs(text: str) -> str:
    """去除重复段落"""
    paragraphs = text.split('\n\n')
    seen = set()
    unique = []
    for p in paragraphs:
        p_stripped = p.strip()
        if p_stripped and p_stripped not in seen:
            seen.add(p_stripped)
            unique.append(p)
        elif not p_stripped:
            unique.append(p)  # 保留空行
    return '\n\n'.join(unique)


def _merge_consecutive_same_role(messages: List[Dict]) -> List[Dict]:
    """合并连续相同 role 的消息"""
    if len(messages) <= 1:
        return messages

    merged = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"] and msg["role"] != "system":
            # 合并内容
            merged[-1]["content"] = merged[-1]["content"] + "\n" + msg["content"]
        else:
            merged.append(msg)
    return merged
