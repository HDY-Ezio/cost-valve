"""
节能阀 Cost Valve - LLM 提供商适配器
AI API 成本优化中间件 - 开源版

厂商适配器模式：统一 OpenAI 兼容 API 格式，透明转发到各 LLM 厂商
支持所有 OpenAI 兼容格式的模型供应商
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
                    last_error = f"提供商 {self.name} 超时 (尝试 {attempt+1}/{self.max_retries})"
                    logger.warning(last_error)
                    if attempt < self.max_retries - 1:
                        await self._backoff(attempt)
                except httpx.HTTPStatusError as e:
                    # 上游 HTTP 错误 → 原样透传
                    error_body = e.response.text
                    logger.error(f"提供商 {self.name} HTTP 错误: {e.response.status_code} {error_body[:200]}")
                    return self._passthrough_error(e.response.status_code, error_body)
                except Exception as e:
                    last_error = f"提供商 {self.name} 错误: {str(e)}"
                    logger.error(last_error)
                    if attempt < self.max_retries - 1:
                        await self._backoff(attempt)

            # 所有重试失败
            return self._passthrough_error(502, json.dumps({
                "error": {"message": last_error or "All retries exhausted", "type": "upstream_error"}
            }))

    async def chat_completion_stream(self, payload: Dict[str, Any]) -> AsyncIterator[str]:
        """流式 Chat Completion (SSE)"""
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
                    "error": {"message": f"提供商 {self.name} 流式超时", "type": "timeout"}
                })
                yield f"data: {error_data}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error(f"提供商 {self.name} 流式错误: {e}")
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
            logger.info(f"提供商已注册: {name}")

        self._initialized = True

    def get(self, name: str) -> Optional[ProviderAdapter]:
        self.initialize()
        return self._providers.get(name)

    def get_all(self) -> Dict[str, ProviderAdapter]:
        self.initialize()
        return dict(self._providers)

    def get_default(self) -> Optional[ProviderAdapter]:
        self.initialize()
        if not self._providers:
            return None
        return next(iter(self._providers.values()))

    def register(self, name: str, adapter: ProviderAdapter):
        self._providers[name] = adapter
        logger.info(f"提供商已注册: {name}")


# 全局注册中心
registry = ProviderRegistry()
