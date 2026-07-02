"""
AI Cost Optimizer - Core Proxy Engine
API 代理核心：接收请求 → 决策 → 缓存 → 调度 → 转发 → 记录
稳定性第一，所有关键环节 try-except 包裹，绝不让代理层自身抛出异常
"""
import json
import time
import logging
import asyncio
from typing import Dict, Any, Optional, AsyncIterator, Tuple

from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from config import get_config
from models import (
    ChatCompletionRequest, TaskPriority, CacheType,
    generate_request_id, now_iso
)
from core.auth import authenticate
from core.providers import registry, ProviderAdapter, ProviderConfig
from core.scheduler import is_peak_time, should_delay, get_next_offpeak
from core.cache import (
    make_cache_key, get_exact_cache, set_exact_cache,
    get_semantic_cache, set_semantic_cache
)
from core.prefix_optimizer import optimize_prefix, analyze_cacheability
from core.savings import calculate_savings
from core.router import select_model, estimate_complexity
from core.prompt_optimizer import optimize_messages
from core.fallback import execute_with_fallback, stream_with_fallback
from core.budget import check_budget, check_quota, calculate_proxy_fee, BudgetAction
from core.usage import record_call

logger = logging.getLogger(__name__)


# ============================================================
# 非流式处理
# ============================================================

async def process_chat_completion(request: ChatCompletionRequest,
                                  api_key_info: Dict,
                                  upstream_adapter=None) -> JSONResponse:
    """
    处理非流式 Chat Completion 请求
    完整流程：认证 → 预算 → 缓存 → 调度 → 优化 → 转发 → 记录
    upstream_adapter：用户自带的上游适配器（X-Upstream-Key），有则直接用，无则走服务端默认
    """
    request_id = generate_request_id()
    start_time = time.time()

    try:
        api_key_id = api_key_info["key_id"]
        messages = [m.dict() for m in request.messages]

        # ============================================================
        # Step 1: 预算检查
        # ============================================================
        try:
            budget_action, budget_info = check_budget(api_key_id)
            if budget_action == BudgetAction.BLOCK:
                return JSONResponse(
                    status_code=429,
                    content=_make_error("budget_exceeded",
                                        f"预算已超出: {budget_info.get('spent_this_month', 0):.2f}/"
                                        f"{budget_info.get('monthly_budget', 0):.2f}元",
                                        request_id)
                )
        except Exception as e:
            logger.error(f"Budget check failed (non-blocking): {e}")
            budget_action = BudgetAction.ALLOW

        # ============================================================
        # Step 2: 配额检查
        # ============================================================
        proxy_fee = 0.0
        try:
            quota_ok, quota_info = check_quota(api_key_id)
            if not quota_ok:
                return JSONResponse(
                    status_code=429,
                    content=_make_error("quota_exceeded",
                                        quota_info.get("message", "月度配额已用完"),
                                        request_id)
                )
            proxy_fee = quota_info.get("proxy_fee", 0.0)
        except Exception as e:
            logger.error(f"Quota check failed (non-blocking): {e}")

        # ============================================================
        # Step 3: 检查缓存（精确 → 语义）
        # ============================================================
        cache_result = None
        try:
            if request.enable_cache:
                # 3a: 精确缓存
                cache_result = await get_exact_cache(
                    request.model, messages, request.temperature, request.max_tokens
                )
                if not cache_result and request.enable_semantic_cache:
                    # 3b: 语义缓存
                    cache_result = await get_semantic_cache(request.model, messages)
        except Exception as e:
            logger.error(f"Cache check failed (non-blocking): {e}")

        if cache_result:
            # 缓存命中 → 直接返回，不计次
            response = cache_result["response"]

            # 计算网关缓存命中的节省金额（等于原本需要的全部费用）
            cache_savings = calculate_savings(
                input_tokens=cache_result.get("input_tokens", 0),
                output_tokens=cache_result.get("output_tokens", 0),
                model=cache_result.get("model", request.model),
                cache_type=cache_result["cache_type"],
            )

            _add_optimization_headers(response, {
                "cache_hit": cache_result["cache_type"],
                "proxy_request_id": request_id,
                "savings": cache_savings.get("savings_breakdown", {}),
            })

            # 记录用量（缓存命中，不计费，但记录节省）
            try:
                gw_savings_json = cache_savings.get("savings_breakdown", {})
                gw_savings_json["total_saved"] = cache_savings.get("total_saved", 0)
                record_call(
                    api_key_id=api_key_id, request_id=request_id,
                    provider=cache_result.get("provider", ""),
                    model=cache_result.get("model", ""),
                    input_tokens=cache_result.get("input_tokens", 0),
                    output_tokens=cache_result.get("output_tokens", 0),
                    original_cost=cache_savings.get("original_cost", 0),
                    actual_cost=0.0,
                    saved_cost=cache_savings.get("total_saved", 0),
                    cache_type=CacheType(cache_result["cache_type"]),
                    proxy_fee=0.0,
                    savings_json=gw_savings_json,
                )
            except Exception as e:
                logger.error(f"Cache hit usage record failed: {e}")

            return JSONResponse(content=response)

        # ============================================================
        # Step 4: 峰谷调度判断
        # ============================================================
        was_delayed = False
        scheduled_at = ""
        try:
            need_delay, delay_time = should_delay(request.priority)
            if need_delay and delay_time:
                # 非紧急任务 + 当前高峰 → 可选择延迟
                # MVP 阶段：记录但不实际延迟（避免复杂性）
                # 后续可改为返回 202 Accepted + 异步回调
                was_delayed = False  # 暂不实际延迟
                logger.info(f"Task could be delayed to {delay_time.isoformat()}")
        except Exception as e:
            logger.error(f"Scheduling check failed (non-blocking): {e}")

        # ============================================================
        # Step 5: 前缀优化（最大化上游缓存命中）
        # ============================================================
        prefix_tokens_optimized = 0
        cacheability_info = {}
        try:
            optimized_messages, prefix_tokens_optimized = optimize_prefix(messages)
            cacheability_info = analyze_cacheability(optimized_messages)
        except Exception as e:
            logger.error(f"Prefix optimization failed (non-blocking): {e}")
            optimized_messages = messages

        # ============================================================
        # Step 6: Prompt 瘦身
        # ============================================================
        tokens_saved = 0
        try:
            if request.enable_prompt_optimize:
                optimized_messages, tokens_saved = optimize_messages(optimized_messages)
        except Exception as e:
            logger.error(f"Prompt optimization failed (non-blocking): {e}")

        # ============================================================
        # Step 7: 直接用用户的上游，不路由不替换
        # ============================================================
        model_name = request.model or upstream_adapter.default_model

        # ============================================================
        # Step 8: 构建转发请求并执行
        # ============================================================
        forward_payload = _build_forward_payload(optimized_messages, model_name, request)
        actual_provider = upstream_adapter.name

        try:
            result = await upstream_adapter.chat_completion(forward_payload)
        except Exception as e:
            logger.error(f"Forward execution failed: {e}")
            return JSONResponse(
                status_code=502,
                content=_make_error("upstream_error", str(e), request_id)
            )

        # 上游错误直接透传
        if "error" in result:
            status_code = result.pop("_status_code", 502)
            return JSONResponse(status_code=status_code, content=result)

        actual_provider = upstream_adapter.name

        # ============================================================
        # Step 9: 写入缓存
        # ============================================================
        try:
            cache_key = make_cache_key(model_name, optimized_messages,
                                       request.temperature, request.max_tokens)
            await set_exact_cache(cache_key, result, actual_provider, model_name,
                                  result.get("usage", {}).get("prompt_tokens", 0),
                                  result.get("usage", {}).get("completion_tokens", 0))
            await set_semantic_cache(model_name, optimized_messages, result,
                                     actual_provider,
                                     result.get("usage", {}).get("prompt_tokens", 0),
                                     result.get("usage", {}).get("completion_tokens", 0))
        except Exception as e:
            logger.error(f"Cache write failed (non-blocking): {e}")

        # ============================================================
        # Step 10: 解析上游缓存命中信息 & 计算节省
        # ============================================================
        upstream_cache_hit_tokens = 0
        savings_info = {}
        try:
            usage = result.get("usage", {})
            # DeepSeek: prompt_cache_hit_tokens / prompt_cache_miss_tokens
            # OpenAI: usage.prompt_tokens_details.cached_tokens
            upstream_cache_hit_tokens = (
                usage.get("prompt_cache_hit_tokens", 0)
                or (usage.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)
            )

            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            savings_info = calculate_savings(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=model_name,
                cache_type="none",  # 这里不是网关缓存命中
                upstream_cache_hit_tokens=upstream_cache_hit_tokens,
                prefix_tokens_optimized=prefix_tokens_optimized,
            )
        except Exception as e:
            logger.error(f"Savings calculation failed (non-blocking): {e}")
            savings_info = {"original_cost": 0, "actual_cost": 0, "total_saved": 0, "savings_breakdown": {}}

        # ============================================================
        # Step 11: 计算成本 & 记录用量
        # ============================================================
        try:
            input_tokens = result.get("usage", {}).get("prompt_tokens", 0)
            output_tokens = result.get("usage", {}).get("completion_tokens", 0)
            peak = is_peak_time()

            original_cost = savings_info.get("original_cost", 0)
            actual_cost = savings_info.get("actual_cost", 0)
            saved_cost = savings_info.get("total_saved", 0)

            # 将节省明细存入 usage 记录
            savings_json = savings_info.get("savings_breakdown", {})
            savings_json["total_saved"] = saved_cost

            record_call(
                api_key_id=api_key_id, request_id=request_id,
                provider=actual_provider, model=model_name,
                input_tokens=input_tokens, output_tokens=output_tokens,
                original_cost=original_cost, actual_cost=actual_cost,
                saved_cost=saved_cost, cache_type=CacheType.NONE,
                was_offpeak=not peak, priority=request.priority.value,
                was_delayed=was_delayed, tokens_saved=tokens_saved,
                proxy_fee=proxy_fee,
                savings_json=savings_json,
            )
        except Exception as e:
            logger.error(f"Usage recording failed (non-blocking): {e}")

        # ============================================================
        # Step 12: 扣余额 + 检查提醒
        # ============================================================
        try:
            from db.database import get_db
            db = get_db()
            if proxy_fee > 0:
                db.deduct_balance(api_key_id, proxy_fee)
            # 检查是否需要发送用量提醒
            reminder = db.check_and_mark_reminder(api_key_id)
            if reminder:
                logger.warning(
                    f"[ALERT] Key '{reminder['name']}' 免费额度即将用完！"
                    f"剩余 {reminder['remaining_free']} 次，阈值 {reminder['alert_threshold']}"
                )
        except Exception as e:
            logger.error(f"Post-call deduction/reminder failed: {e}")

        # 添加优化头信息
        _add_optimization_headers(result, {
            "proxy_request_id": request_id,
            "provider": actual_provider,
            "model": model_name,
            "tokens_saved": tokens_saved,
            "prefix_tokens_optimized": prefix_tokens_optimized,
            "cache_hit": "none",
            "upstream_cache_hit_tokens": upstream_cache_hit_tokens,
            "cacheability": cacheability_info,
            "savings": savings_info.get("savings_breakdown", {}),
        })

        return JSONResponse(content=result)

    except Exception as e:
        # 最后的安全网：任何未预期的异常
        logger.critical(f"UNHANDLED EXCEPTION in process_chat_completion: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=_make_error("internal_error", "Internal proxy error", request_id)
        )


# ============================================================
# 流式处理
# ============================================================

async def process_stream_chat_completion(request: ChatCompletionRequest,
                                         api_key_info: Dict,
                                         upstream_adapter=None) -> StreamingResponse:
    """
    处理流式 Chat Completion 请求
    核心原则：逐 chunk 透传，不缓冲，不修改
    upstream_adapter：用户自带的上游适配器，有则直接用
    """
    request_id = generate_request_id()

    try:
        api_key_id = api_key_info["key_id"]
        messages = [m.dict() for m in request.messages]

        # ============================================================
        # 前置检查（同非流式，但简化）
        # ============================================================

        # 预算检查
        try:
            budget_action, budget_info = check_budget(api_key_id)
            if budget_action == BudgetAction.BLOCK:
                async def _blocked_stream():
                    error = json.dumps(_make_error("budget_exceeded",
                                                   "预算已超出", request_id))
                    yield f"data: {error}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(_blocked_stream(), media_type="text/event-stream")
        except Exception as e:
            logger.error(f"Budget check failed in stream: {e}")

        # 配额检查
        proxy_fee = 0.0
        try:
            quota_ok, quota_info = check_quota(api_key_id)
            if not quota_ok:
                async def _quota_exceeded_stream():
                    error = json.dumps(_make_error("quota_exceeded",
                                                   quota_info.get("message", "配额已用完"), request_id))
                    yield f"data: {error}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(_quota_exceeded_stream(), media_type="text/event-stream")
            proxy_fee = quota_info.get("proxy_fee", 0.0)
        except Exception as e:
            logger.error(f"Quota check failed in stream: {e}")

        # 缓存检查（流式也可以用缓存）
        try:
            if request.enable_cache:
                cache_result = await get_exact_cache(
                    request.model, messages, request.temperature, request.max_tokens
                )
                if not cache_result and request.enable_semantic_cache:
                    cache_result = await get_semantic_cache(request.model, messages)

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
                                api_key_id=api_key_id, request_id=request_id,
                                provider=cache_result.get("provider", ""),
                                model=cache_result.get("model", ""),
                                input_tokens=cache_result.get("input_tokens", 0),
                                output_tokens=cache_result.get("output_tokens", 0),
                                original_cost=0.0, actual_cost=0.0, saved_cost=0.0,
                                cache_type=CacheType(cache_result["cache_type"]),
                                proxy_fee=0.0,
                            )
                        except Exception as e:
                            logger.error(f"Stream cache record failed: {e}")

                    return StreamingResponse(_cached_stream(), media_type="text/event-stream")
        except Exception as e:
            logger.error(f"Stream cache check failed: {e}")

        # Prompt 瘦身
        tokens_saved = 0
        optimized_messages = messages
        try:
            if request.enable_prompt_optimize:
                optimized_messages, tokens_saved = optimize_messages(messages)
        except Exception as e:
            logger.error(f"Stream prompt optimize failed: {e}")
            optimized_messages = messages

        # 直接用用户的上游，不路由不替换
        model_name = request.model or upstream_adapter.default_model

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
                logger.error(f"Stream generator error: {e}")
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
                    await set_semantic_cache(model_name, optimized_messages, mock_response,
                                             actual_provider, 0, 0)
            except Exception as e:
                logger.error(f"Stream post-cache failed: {e}")

            try:
                record_call(
                    api_key_id=api_key_id, request_id=request_id,
                    provider=actual_provider, model=model_name,
                    input_tokens=0, output_tokens=len("".join(collected_content)) // 4,
                    original_cost=0.0, actual_cost=0.0, saved_cost=0.0,
                    cache_type=CacheType.NONE,
                    priority=request.priority.value,
                    tokens_saved=tokens_saved,
                    proxy_fee=proxy_fee,
                )
                # 扣余额 + 检查提醒
                from db.database import get_db
                db = get_db()
                if proxy_fee > 0:
                    db.deduct_balance(api_key_id, proxy_fee)
                reminder = db.check_and_mark_reminder(api_key_id)
                if reminder:
                    logger.warning(
                        f"[ALERT] Key '{reminder['name']}' 免费额度即将用完！"
                        f"剩余 {reminder['remaining_free']} 次"
                    )
            except Exception as e:
                logger.error(f"Stream usage record failed: {e}")

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
        logger.critical(f"UNHANDLED EXCEPTION in stream handler: {e}", exc_info=True)

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


def _add_optimization_headers(response: Dict, info: Dict):
    """在响应中添加优化信息（以自定义字段形式）"""
    try:
        response["_optimization"] = {
            "request_id": info.get("proxy_request_id", ""),
            "provider": info.get("provider", ""),
            "model": info.get("model", ""),
            "cache_hit": info.get("cache_hit", "none"),
            "tokens_saved": info.get("tokens_saved", 0),
        }
    except Exception:
        pass  # 不影响主流程
