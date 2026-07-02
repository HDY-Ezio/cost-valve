"""
AI Cost Optimizer - Smart Model Router
根据任务复杂度自动选择最合适的模型
"""
import logging
from typing import Dict, List, Optional, Tuple

from config import get_config
from models import TaskPriority

logger = logging.getLogger(__name__)


def estimate_complexity(messages: List[Dict]) -> str:
    """
    估算任务复杂度: simple / medium / complex

    判断依据:
    - 消息总长度 (字符数)
    - 消息轮数
    - 是否有 system prompt
    - 是否包含代码块、长文本
    """
    try:
        total_chars = sum(len(m.get("content", "")) for m in messages)
        msg_count = len(messages)
        has_system = any(m.get("role") == "system" for m in messages)

        # 检查是否包含代码
        has_code = any("```" in m.get("content", "") or "def " in m.get("content", "")
                       or "class " in m.get("content", "") or "function " in m.get("content", "")
                       for m in messages)

        # 检查是否有长文本 (>2000字符视为长文本)
        has_long_text = any(len(m.get("content", "")) > 2000 for m in messages)

        # 复杂度评分
        score = 0
        score += min(total_chars / 500, 5)     # 文本长度贡献 (0-5)
        score += min(msg_count / 3, 3)          # 对话轮数贡献 (0-3)
        if has_system:
            score += 1
        if has_code:
            score += 2
        if has_long_text:
            score += 2

        if score <= 3:
            return "simple"
        elif score <= 7:
            return "medium"
        else:
            return "complex"
    except Exception as e:
        logger.error(f"estimate_complexity error: {e}")
        return "medium"  # 出错时默认中等


def select_model(messages: List[Dict], requested_model: str = "",
                 priority: TaskPriority = TaskPriority.IMMEDIATE) -> Tuple[str, str]:
    """
    选择最优模型

    Args:
        messages: 消息列表
        requested_model: 用户指定的模型（如果指定则优先使用）
        priority: 任务优先级

    Returns:
        (provider_name, model_name)
    """
    try:
        cfg = get_config()

        # 如果用户明确指定了模型，尊重用户选择
        if requested_model:
            provider = _find_provider_for_model(requested_model)
            if provider:
                return provider, requested_model
            # 指定的模型不在已知列表中，使用默认 provider
            return "deepseek", requested_model

        # 智能路由
        if not cfg.router_enabled:
            # 路由关闭，使用默认
            return "deepseek", cfg.simple_model

        complexity = estimate_complexity(messages)
        logger.info(f"Task complexity: {complexity}")

        if complexity == "simple":
            # 简单任务 → 小模型（便宜10倍）
            model = cfg.simple_model
        elif complexity == "complex" or priority == TaskPriority.IMMEDIATE:
            # 复杂任务或紧急任务 → 大模型
            model = cfg.complex_model
        else:
            # 中等任务 → 中间模型
            model = cfg.simple_model  # MVP 阶段先用简单模型

        provider = _find_provider_for_model(model) or "deepseek"
        return provider, model
    except Exception as e:
        logger.error(f"select_model error: {e}")
        return "deepseek", get_config().simple_model


def _find_provider_for_model(model: str) -> Optional[str]:
    """查找模型对应的提供商"""
    try:
        cfg = get_config()
        for name, provider_cfg in cfg.providers.items():
            if model == provider_cfg.model or model in provider_cfg.models:
                return name
        return None
    except Exception:
        return None


def get_routing_info(messages: List[Dict], requested_model: str = "") -> Dict:
    """获取路由信息（用于 API 返回/调试）"""
    try:
        complexity = estimate_complexity(messages)
        provider, model = select_model(messages, requested_model)
        return {
            "complexity": complexity,
            "selected_provider": provider,
            "selected_model": model,
            "requested_model": requested_model,
            "router_enabled": get_config().router_enabled,
        }
    except Exception as e:
        logger.error(f"get_routing_info error: {e}")
        return {"error": str(e)}
