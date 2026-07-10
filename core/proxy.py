"""
节能阀 Cost Valve - 核心代理引擎
AI API 成本优化中间件 - 开源版

API 代理核心：接收请求 → 缓存 → 优化 → 转发 → 记录
稳定性第一，所有关键环节 try-except 包裹
"""
import json
import time
import logging
from typing import Dict, Any, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from config import get_config, ProviderConfig
from models import (
    ChatCompletionRequest, CacheType,
    generate_request_id,
)
from core.cache import make_cache_key, get_exact_cache, set_exact_cache
from core.prefix_optimizer import optimize_prefix, analyze_cacheability
from core.prompt_optimizer import optimize_messages
from core.providers import registry, ProviderAdapter
from core.usage import record_call

logger = logging.getLogger(__name__)


# ============================================================
# 非流式处理
# ============================================================

async def process_chat_completion(
    request: ChatCompletionRequest,
    upstream_adapter: ProviderAdapter,
) -> JSONResponse:
    """
    处理非流式 Chat Completion 请求
    
    完整流程：缓存检查 → 前缀优化 → Prompt 瘦身 → 转发 → 写缓存 → 记录
    
    Args:
        request: Chat Completion 请求
        upstream_adapter: 上游提供商适配器
    
    Returns:
        JSONResponse
    """
    request_id = generate_request_id()
    start_time = time.time()

    try:
        messages = [m.dict() for m in request.messages]
        model_name = request.model or upstream_adapter.default_model

        # ============================================================
        # Step 1: 检查精确缓存
        # ============================================================
        cache_result = None
        try:
            if request.enable_cache:
                cache_result = await get_exact_cache(
                    model_name, messages, request.temperature, request.max_tokens
                )
        except Exception as e:
            logger.error(f"缓存检查失败 (非阻塞): {e}")

        if cache_result:
            # 缓存命中 → 直接返回
            response = cache_result["response"]
            _add_optimization_info(response, {
                "request_id": request_id,
                "cache_hit": cache_result["cache_type"],
                "provider": cache_result.get("provider", ""),
                "model": cache_result.get("model", ""),
            })

            # 记录缓存命中
            try:
                record_call(
                    request_id=request_id,
                    provider=cache_result.get("provider", ""),
                    model=cache_result.get("model", ""),
                    input_tokens=cache_result.get("input_tokens", 0),
                    output_tokens=cache_result.get("output_tokens", 0),
                    cache_type=CacheType.EXACT,
                    tokens_saved=cache_result.get("input_tokens", 0) + cache_result.get("output_tokens", 0),
                )
            except Exception as e:
                logger.error(f"缓存命中记录失败: {e}")

            return JSONResponse(content=response)

        # ============================================================
        # Step 2: 前缀优化（最大化上游缓存命中）
        # ============================================================
        prefix_tokens_optimized = 0
        cacheability_info = {}
        try:
            optimized_messages, prefix_tokens_optimized = optimize_prefix(messages)
            cacheability_info = analyze_cacheability(optimized_messages)
        except Exception as e:
            logger.error(f"前缀优化失败 (非阻塞): {e}")
            optimized_messages = messages

        # ============================================================
        # Step 3: Prompt 瘦身
        # ============================================================
        tokens_saved = 0
        try:
            if request.enable_prompt_optimize:
                optimized_messages, tokens_saved = optimize_messages(optimized_messages)
        except Exception as e:
            logger.error(f"Prompt 瘦身失败 (非阻塞): {e}")

        # ============================================================
        # Step 4: 构建转发请求并执行
        # ============================================================
        forward_payload = _build_forward_payload(optimized_messages, model_name, request)
        actual_provider = upstream_adapter.name

        try:
            result = await upstream_adapter.chat_completion(forward_payload)
        except Exception as e:
            logger.error(f"上游请求失败: {e}")
            return JSONResponse(
                status_code=502,
                content=_make_error("upstream_error", str(e), request_id)
            )

        # 上游错误直接透传
        if "error" in result:
            status_code = result.pop("_status_code", 502)
            return JSONResponse(status_code=status_code, content=result)

        # ============================================================
        # Step 5: 写入精确缓存
        # ============================================================
        try:
            cache_key = make_cache_key(model_name, optimized_messages,
                                       request.temperature, request.max_tokens)
            await set_exact_cache(
                cache_key, result, actual_provider, model_name,
                result.get("usage", {}).get("prompt_tokens", 0),
                result.get("usage", {}).get("completion_tokens", 0),
            )
        except Exception as e:
            logger.error(f"缓存写入失败 (非阻塞): {e}")

        # ============================================================
        # Step 6: 记录用量
        # ============================================================
        try:
            input_tokens = result.get("usage", {}).get("prompt_tokens", 0)
            output_tokens = result.get("usage", {}).get("completion_tokens", 0)

            record_call(
                request_id=request_id,
                provider=actual_provider,
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_type=CacheType.NONE,
                tokens_saved=tokens_saved + prefix_tokens_optimized,
            )
        except Exception as e:
            logger.error(f"用量记录失败 (非阻塞): {e}")

        # 添加优化信息
        _add_optimization_info(result, {
            "request_id": request_id,
            "provider": actual_provider,
            "model": model_name,
            "cache_hit": "none",
            "tokens_saved": tokens_saved,
            "prefix_tokens_optimized": prefix_tokens_optimized,
            "cacheability": cacheability_info,
            "processing_time_ms": round((time.time() - start_time) * 1000, 2),
        })

        return JSONResponse(content=result)

    except Exception as e:
        # 最后的安全网：任何未预期的异常
        logger.critical(f"代理处理未预期异常: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=_make_error("internal_error", "Internal proxy error", request_id)
        )


# ============================================================
# 流式处理
# ============================================================

async def process_stream_chat_completion(
    request: ChatCompletionRequest,
    upstream_adapter: ProviderAdapter,
) -> StreamingResponse:
    """
    处理流式 Chat Completion 请求
    
    核心原则：逐 chunk 透传，不缓冲，不修改
    
    Args:
        request: Chat Completion 请求
        upstream_adapter: 上游提供商适配器
    
    Returns:
        StreamingResponse
    """
    request_id = generate_request_id()

    try:
        messages = [m.dict() for m in request.messages]
        model_name = request.model or upstream_adapter.default_model

        # ============================================================
        # 前置检查：精确缓存（流式也可以用缓存）
        # ============================================================
        try:
            if request.enable_cache:
                cache_result = await get_exact_cache(
                    model_name, messages, request.temperature, request.max_tokens
                )

                if cache_result:
                    # 缓存命中 → 把缓存结果转为流式输出
                    async def _cached_stream():
                        response = cache_result["response"]
                        content = ""
                        for choice in response.get("choices", []):
                            msg = choice.get("message", {}) or choice.get("delta", {})
                            content = msg.get("content", "")
                        if content:
                            # 模拟流式输出缓存内容
                            chunk = json.dumps({
                                "id": f"cache-{request_id}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": cache_result.get("model", ""),
                                "choices": [{"index": 0, "delta": {"role": "assistant", "content": content},
                                             "finish_reason": None}]
                            })
                            yield f"data: {chunk}\n\n"
                            # Final chunk
                            final = json.dumps({
                                "id": f"cache-{request_id}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": cache_result.get("model", ""),
                                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                            })
                            yield f"data: {final}\n\n"
                            yield "data: [DONE]\n\n"

                        # 记录缓存命中
                        try:
                            record_call(
                                request_id=request_id,
                                provider=cache_result.get("provider", ""),
                                model=cache_result.get("model", ""),
                                input_tokens=cache_result.get("input_tokens", 0),
                                output_tokens=cache_result.get("output_tokens", 0),
                                cache_type=CacheType.EXACT,
                                tokens_saved=cache_result.get("input_tokens", 0) + cache_result.get("output_tokens", 0),
                            )
                        except Exception as e:
                            logger.error(f"流式缓存记录失败: {e}")

                    return StreamingResponse(_cached_stream(), media_type="text/event-stream")
        except Exception as e:
            logger.error(f"流式缓存检查失败: {e}")

        # ============================================================
        # 前缀优化 + Prompt 瘦身
        # ============================================================
        tokens_saved = 0
        optimized_messages = messages
        try:
            optimized_messages, _ = optimize_prefix(messages)
            if request.enable_prompt_optimize:
                optimized_messages, tokens_saved = optimize_messages(optimized_messages)
        except Exception as e:
            logger.error(f"流式优化失败: {e}")
            optimized_messages = messages

        # 构建转发请求
        forward_payload = _build_forward_payload(optimized_messages, model_name, request)
        actual_provider = upstream_adapter.name

        # ============================================================
        # 流式转发（核心：逐 chunk 透传）
        # ============================================================
        collected_content = []

        async def _stream_generator():
            """流式生成器：透传上游 SSE，同时收集内容用于缓存"""
            try:
                async for chunk in upstream_adapter.chat_completion_stream(forward_payload):
                    # 透传每个 chunk
                    yield chunk
                    # 收集内容（非阻塞，用于后续缓存）
                    try:
                        if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                            data_str = chunk[6:].strip()
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                if delta and delta.get("content"):
                                    collected_content.append(delta["content"])
                    except (json.JSONDecodeError, KeyError, IndexError):
                        pass  # 解析失败不影响透传

            except Exception as e:
                logger.error(f"流生成器错误: {e}")
                # 透传错误给客户端
                error = json.dumps({"error": {"message": str(e), "type": "stream_error"}})
                yield f"data: {error}\n\n"
                yield "data: [DONE]\n\n"

            # 流结束后：写缓存 + 记录用量（异步，不阻塞响应）
            try:
                full_content = "".join(collected_content)
                if full_content:
                    cache_key = make_cache_key(model_name, optimized_messages,
                                               request.temperature, request.max_tokens)
                    mock_response = {
                        "choices": [{"message": {"role": "assistant", "content": full_content}}],
                        "usage": {"prompt_tokens": 0, "completion_tokens": len(full_content) // 4}
                    }
                    await set_exact_cache(cache_key, mock_response, actual_provider, model_name, 0, 0)
            except Exception as e:
                logger.error(f"流式后缓存写入失败: {e}")

            try:
                record_call(
                    request_id=request_id,
                    provider=actual_provider,
                    model=model_name,
                    input_tokens=0,
                    output_tokens=len("".join(collected_content)) // 4,
                    cache_type=CacheType.NONE,
                    tokens_saved=tokens_saved,
                )
            except Exception as e:
                logger.error(f"流式用量记录失败: {e}")

        return StreamingResponse(
            _stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Nginx 不要缓冲
                "X-Proxy-Request-Id": request_id,
            }
        )

    except Exception as e:
        logger.critical(f"流式处理未预期异常: {e}", exc_info=True)

        async def _error_stream():
            error = json.dumps(_make_error("internal_error", "Internal proxy error", request_id))
            yield f"data: {error}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_error_stream(), media_type="text/event-stream")


# ============================================================
# 辅助函数
# ============================================================

def _build_forward_payload(messages: list, model: str, request: ChatCompletionRequest) -> Dict:
    """构建转发给上游 LLM 的请求体"""
    payload = {
        "model": model,
        "messages": messages,
        "stream": request.stream,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    return payload


def _make_error(error_type: str, message: str, request_id: str = "") -> Dict:
    """构造 OpenAI 兼容的错误响应"""
    return {
        "error": {
            "message": message,
            "type": error_type,
            "code": error_type,
        },
        "request_id": request_id,
    }


def _add_optimization_info(response: Dict, info: Dict):
    """在响应中添加优化信息（以自定义字段形式）"""
    try:
        response["_optimization"] = info
    except Exception:
        pass  # 不影响主流程
