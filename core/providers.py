"""
AI Cost Optimizer - LLM Provider Adapters
厂商适配器模式：统一 OpenAI 兼容 API 格式，透明转发到各 LLM 厂商
"""
import json
import time
import logging
from typing import Dict, Any, AsyncIterator, Optional

import httpx

from config import get_config, ProviderConfig

logger = logging.getLogger(__name__)


class ProviderAdapter:
    """LLM 提供商适配器基类"""

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.name = config.name
        self.base_url = config.base_url.rstrip("/")
        self.api_key = config.api_key
        self.default_model = config.model
        self.timeout = config.timeout
        self.max_retries = config.max_retries
        self.is_mock = config.is_mock

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_url(self, path: str = "/v1/chat/completions") -> str:
        return f"{self.base_url}{path}"

    async def chat_completion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """非流式 Chat Completion"""
        if self.is_mock:
            return self._mock_response(payload)

        url = self._build_url()
        headers = self._headers()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            last_error = None
            for attempt in range(self.max_retries):
                try:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    return resp.json()
                except httpx.TimeoutException as e:
                    last_error = f"Provider {self.name} timeout (attempt {attempt+1}/{self.max_retries})"
                    logger.warning(last_error)
                    if attempt < self.max_retries - 1:
                        await self._backoff(attempt)
                except httpx.HTTPStatusError as e:
                    # 上游 HTTP 错误 → 原样透传
                    error_body = e.response.text
                    logger.error(f"Provider {self.name} HTTP error: {e.response.status_code} {error_body[:200]}")
                    return self._passthrough_error(e.response.status_code, error_body)
                except Exception as e:
                    last_error = f"Provider {self.name} error: {str(e)}"
                    logger.error(last_error)
                    if attempt < self.max_retries - 1:
                        await self._backoff(attempt)

            # 所有重试失败
            return self._passthrough_error(502, json.dumps({
                "error": {"message": last_error or "All retries exhausted", "type": "upstream_error"}
            }))

    async def chat_completion_stream(self, payload: Dict[str, Any]) -> AsyncIterator[str]:
        """流式 Chat Completion (SSE)"""
        if self.is_mock:
            async for chunk in self._mock_stream_response(payload):
                yield chunk
            return

        url = self._build_url()
        headers = self._headers()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        # 上游错误 → 原样透传
                        body = await resp.aread()
                        error_data = json.dumps({
                            "error": {
                                "message": f"Upstream error: {resp.status_code}",
                                "type": "upstream_error",
                                "detail": body.decode("utf-8", errors="replace")[:500]
                            }
                        })
                        yield f"data: {error_data}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    # 逐行透传 SSE
                    async for line in resp.aiter_lines():
                        if line:
                            yield f"{line}\n\n"
            except httpx.TimeoutException:
                error_data = json.dumps({
                    "error": {"message": f"Provider {self.name} streaming timeout", "type": "timeout"}
                })
                yield f"data: {error_data}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error(f"Stream error from {self.name}: {e}")
                error_data = json.dumps({
                    "error": {"message": str(e), "type": "stream_error"}
                })
                yield f"data: {error_data}\n\n"
                yield "data: [DONE]\n\n"

    async def _backoff(self, attempt: int):
        """指数退避"""
        import asyncio
        wait = min(2 ** attempt, 8)
        await asyncio.sleep(wait)

    def _passthrough_error(self, status_code: int, body: str) -> Dict:
        """构造透传错误响应"""
        try:
            error_json = json.loads(body)
            return {"error": error_json.get("error", {"message": body, "type": "upstream_error"}),
                    "_status_code": status_code}
        except (json.JSONDecodeError, AttributeError):
            return {"error": {"message": body[:500], "type": "upstream_error"},
                    "_status_code": status_code}

    # ============================================================
    # Mock 响应（无需真实 API Key 即可测试）
    # ============================================================

    def _mock_response(self, payload: Dict) -> Dict:
        """生成 mock 非流式响应"""
        import uuid as _uuid
        messages = payload.get("messages", [])
        last_msg = messages[-1]["content"] if messages else ""

        # 模拟回复
        content = f"[Mock Response from {self.name}] You said: {last_msg[:100]}"
        input_tokens = sum(len(m.get("content", "")) for m in messages) // 4
        output_tokens = len(content) // 4

        return {
            "id": f"chatcmpl-mock-{_uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model", self.default_model),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens
            }
        }

    async def _mock_stream_response(self, payload: Dict):
        """生成 mock 流式响应"""
        import uuid as _uuid
        import asyncio

        messages = payload.get("messages", [])
        last_msg = messages[-1]["content"] if messages else ""
        content = f"[Mock Stream from {self.name}] Reply: {last_msg[:80]}"
        model = payload.get("model", self.default_model)
        req_id = f"chatcmpl-mock-{_uuid.uuid4().hex[:8]}"
        created = int(time.time())

        # Role chunk
        role_chunk = json.dumps({
            "id": req_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
        })
        yield f"data: {role_chunk}\n\n"

        # Content chunks (simulate streaming word by word)
        words = content.split(" ")
        for i, word in enumerate(words):
            chunk = json.dumps({
                "id": req_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {"content": word + " "}, "finish_reason": None}]
            })
            yield f"data: {chunk}\n\n"
            await asyncio.sleep(0.02)  # Simulate network delay

        # Final chunk
        final_chunk = json.dumps({
            "id": req_id, "object": "chat.completion.chunk",
            "created": created, "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        })
        yield f"data: {final_chunk}\n\n"
        yield "data: [DONE]\n\n"


# ============================================================
# Provider Registry
# ============================================================

class ProviderRegistry:
    """提供商注册中心"""

    def __init__(self):
        self._providers: Dict[str, ProviderAdapter] = {}
        self._initialized = False

    def initialize(self):
        """从配置初始化所有提供商"""
        if self._initialized:
            return
        cfg = get_config()
        for name, provider_cfg in cfg.providers.items():
            self._providers[name] = ProviderAdapter(provider_cfg)
            logger.info(f"Provider registered: {name} (mock={provider_cfg.is_mock})")

        # 如果没有配置任何 provider，自动注册一个 mock
        if not self._providers:
            mock_cfg = ProviderConfig(
                name="mock",
                base_url="http://localhost",
                api_key="mock-key",
                model="mock-model",
                is_mock=True,
            )
            self._providers["mock"] = ProviderAdapter(mock_cfg)
            logger.info("No providers configured, registered mock provider")

        self._initialized = True

    def get(self, name: str) -> Optional[ProviderAdapter]:
        self.initialize()
        return self._providers.get(name)

    def get_all(self) -> Dict[str, ProviderAdapter]:
        self.initialize()
        return dict(self._providers)

    def get_default(self) -> ProviderAdapter:
        self.initialize()
        if not self._providers:
            raise RuntimeError("No providers available")
        return next(iter(self._providers.values()))

    def register(self, name: str, adapter: ProviderAdapter):
        self._providers[name] = adapter
        logger.info(f"Provider registered: {name}")


# 全局注册中心
registry = ProviderRegistry()
