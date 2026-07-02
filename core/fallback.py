"""
AI Cost Optimizer - Multi-Provider Fallback
主厂商失败时自动切换到备用厂商
"""
import json
import logging
from typing import Dict, Any, Optional, List, AsyncIterator

from core.providers import registry, ProviderAdapter

logger = logging.getLogger(__name__)

# 默认 fallback 顺序
DEFAULT_FALLBACK_ORDER = ["deepseek", "aliyun", "generic", "mock"]


async def execute_with_fallback(payload: Dict[str, Any], is_stream: bool = False,
                                preferred_provider: str = "",
                                exclude_providers: Optional[List[str]] = None) -> Dict:
    """
    带 Fallback 的请求执行

    流程:
    1. 优先使用指定 provider
    2. 失败则按顺序尝试其他 provider
    3. 所有 provider 都失败 → 返回最后一个错误

    Args:
        payload: OpenAI 格式的请求体
        is_stream: 是否流式（流式不 fallback，直接返回）
        preferred_provider: 优先的提供商
        exclude_providers: 排除的提供商列表

    Returns:
        响应 dict，包含 _provider 和 _fallback_useded 字段
    """
    exclude = set(exclude_providers or [])
    providers_to_try = _build_fallback_order(preferred_provider, exclude)

    last_error = None
    for i, provider_name in enumerate(providers_to_try):
        provider = registry.get(provider_name)
        if not provider:
            continue

        try:
            logger.info(f"Trying provider: {provider_name} (attempt {i+1}/{len(providers_to_try)})")
            result = await provider.chat_completion(payload)

            # 检查是否有上游错误
            if "error" in result and "_status_code" in result:
                status = result.get("_status_code", 500)
                if status >= 500:
                    # 服务端错误 → 尝试下一个
                    last_error = result
                    logger.warning(f"Provider {provider_name} returned {status}, trying fallback...")
                    continue
                else:
                    # 客户端错误（4xx）→ 直接透传，不 fallback
                    result["_provider"] = provider_name
                    result["_fallback_used"] = i > 0
                    return result

            # 成功
            result["_provider"] = provider_name
            result["_fallback_used"] = i > 0
            if i > 0:
                logger.info(f"Fallback succeeded with {provider_name}")
            return result

        except Exception as e:
            last_error = {
                "error": {"message": f"Provider {provider_name} failed: {str(e)}", "type": "provider_error"},
                "_status_code": 502
            }
            logger.error(f"Provider {provider_name} exception: {e}")
            continue

    # 所有 provider 都失败
    if last_error:
        return last_error
    return {
        "error": {"message": "No providers available", "type": "no_provider"},
        "_status_code": 503
    }


async def stream_with_fallback(payload: Dict[str, Any], preferred_provider: str = ""
                               ) -> AsyncIterator[str]:
    """
    流式请求（不做 fallback，直接透传）
    流式传输中无法中途切换 provider，所以只尝试一个
    """
    provider_name = preferred_provider or DEFAULT_FALLBACK_ORDER[0]
    provider = registry.get(provider_name)

    if not provider:
        # 尝试任意可用 provider
        for name in DEFAULT_FALLBACK_ORDER:
            provider = registry.get(name)
            if provider:
                provider_name = name
                break

    if not provider:
        error = json.dumps({
            "error": {"message": "No providers available", "type": "no_provider"}
        })
        yield f"data: {error}\n\n"
        yield "data: [DONE]\n\n"
        return

    try:
        async for chunk in provider.chat_completion_stream(payload):
            yield chunk
    except Exception as e:
        logger.error(f"Stream error from {provider_name}: {e}")
        error = json.dumps({
            "error": {"message": f"Stream error: {str(e)}", "type": "stream_error"}
        })
        yield f"data: {error}\n\n"
        yield "data: [DONE]\n\n"


def _build_fallback_order(preferred: str, exclude: set) -> List[str]:
    """构建 fallback 尝试顺序"""
    order = []

    # 首选
    if preferred and preferred not in exclude:
        order.append(preferred)

    # 按默认顺序添加其他
    for name in DEFAULT_FALLBACK_ORDER:
        if name not in order and name not in exclude:
            order.append(name)

    # 添加注册表中可能有但不在默认列表中的
    all_providers = registry.get_all()
    for name in all_providers:
        if name not in order and name not in exclude:
            order.append(name)

    return order
