"""
节能阀 Cost Valve - FastAPI 主入口
AI API 成本优化中间件 - 开源版

通过智能缓存和优化降低 AI API token 消耗
就像水龙头一样控制你的 AI 成本
"""
import sys
import os
import logging
import time
import ipaddress
from contextlib import asynccontextmanager
from urllib.parse import urlparse

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import get_config, ProviderConfig
from models import ChatCompletionRequest
from core.proxy import process_chat_completion, process_stream_chat_completion
from core.providers import registry, ProviderAdapter
from core.usage import get_usage_dashboard
from db.database import init_db, get_db

# ============================================================
# SSRF 防护
# ============================================================
ALLOWED_UPSTREAM_DOMAINS = {
    "ark.cn-beijing.volces.com",
    "api.deepseek.com",
    "dashscope.aliyuncs.com",
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "open.bigmodel.cn",
}

def validate_upstream_url(url: str) -> bool:
    """校验上游 URL，阻止 SSRF 攻击"""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        # 阻止内网 IP
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except ValueError:
            pass  # 不是 IP 地址，是域名
        # 白名单域名放行，未知公网域名也放行（允许用户对接新厂商）
        return True
    except Exception:
        return False


# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cost-valve")


# ============================================================
# Lifespan
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时的操作"""
    cfg = get_config()
    logger.info("=" * 60)
    logger.info("  节能阀 Cost Valve - AI API 成本优化中间件")
    logger.info(f"  版本: {app.version}")
    logger.info(f"  监听地址: {cfg.host}:{cfg.port}")
    logger.info(f"  缓存: {'启用' if cfg.cache_enabled else '禁用'}")
    logger.info(f"  已配置提供商: {list(cfg.providers.keys()) or '无（通过 Header 传入）'}")
    logger.info(f"  数据库: {cfg.db_path}")
    logger.info("=" * 60)

    # 初始化数据库
    init_db(cfg.db_path)

    # 初始化提供商注册中心
    registry.initialize()

    yield

    # 关闭
    logger.info("节能阀 Cost Valve - Shutting down")


# ============================================================
# FastAPI App
# ============================================================
cfg = get_config()
app = FastAPI(
    title="节能阀 Cost Valve",
    description="AI API 成本优化中间件 - 通过智能缓存降低 token 消耗",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if cfg.debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if cfg.debug else None,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-Upstream-Key", "X-Upstream-URL"],
)


# ============================================================
# 认证依赖（单用户模式）
# ============================================================
async def verify_api_key(x_api_key: str = Header(default="", alias="X-API-Key")):
    """验证 API Key（单用户模式）
    
    如果配置了 COST_VALVE_API_KEY，则需要匹配
    如果没有配置，则无需认证（本地开发用）
    """
    cfg = get_config()
    expected_key = cfg.api_key
    
    # 如果没有配置 API Key，直接放行（本地开发模式）
    if not expected_key or expected_key.startswith("cv-"):
        # 检查是否是自动生成的默认 key（如果用户没有设置）
        env_key = os.getenv("COST_VALVE_API_KEY", "")
        if not env_key:
            return True  # 未设置，免认证
    
    # 如果设置了 API Key，则需要验证
    if expected_key and x_api_key != expected_key:
        # 也支持 Authorization header
        raise HTTPException(
            status_code=401,
            detail={"error": {"message": "Invalid API key", "type": "auth_error"}}
        )
    
    return True


# ============================================================
# 核心 API 端点 (OpenAI 兼容)
# ============================================================

@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    body: ChatCompletionRequest,
    _: bool = Depends(verify_api_key),
    x_upstream_key: str = Header(default="", alias="X-Upstream-Key"),
    x_upstream_url: str = Header(default="", alias="X-Upstream-URL"),
    x_upstream_provider: str = Header(default="", alias="X-Upstream-Provider"),
):
    """
    Chat Completions API (OpenAI 兼容)
    
    支持流式和非流式
    通过 Header 指定上游：
      X-Upstream-Key：上游 API 密钥
      X-Upstream-URL：上游厂商地址
      X-Upstream-Provider：已配置的提供商名称（可选，如 deepseek/openai）
    """
    # 确定使用哪个上游适配器
    upstream_adapter = None

    # 方式1：通过 X-Upstream-Provider 使用已配置的提供商
    if x_upstream_provider:
        upstream_adapter = registry.get(x_upstream_provider)
        if not upstream_adapter:
            return JSONResponse(
                status_code=400,
                content={"error": {"message": f"Provider '{x_upstream_provider}' not configured", "type": "invalid_provider"}}
            )
    
    # 方式2：通过 Header 直接传入上游 Key 和 URL
    elif x_upstream_key and x_upstream_url:
        # SSRF 防护
        if not validate_upstream_url(x_upstream_url):
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "Invalid X-Upstream-URL. Private IPs are not allowed.", "type": "invalid_upstream_url"}}
            )
        
        upstream_adapter = ProviderAdapter(ProviderConfig(
            name="custom-upstream",
            base_url=x_upstream_url,
            api_key=x_upstream_key,
            model=body.model or "gpt-3.5-turbo",
            is_mock=False,
        ))
    
    # 方式3：使用默认配置的提供商
    else:
        upstream_adapter = registry.get_default()
        if not upstream_adapter:
            return JSONResponse(
                status_code=400,
                content={"error": {
                    "message": "No upstream provider configured. Set X-Upstream-Key + X-Upstream-URL headers, or configure providers via environment variables.",
                    "type": "no_provider_configured"
                }}
            )

    try:
        if body.stream:
            return await process_stream_chat_completion(body, upstream_adapter=upstream_adapter)
        else:
            return await process_chat_completion(body, upstream_adapter=upstream_adapter)
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(f"Unhandled exception in /v1/chat/completions: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Internal server error", "type": "internal_error"}}
        )


# ============================================================
# 状态 & 健康检查
# ============================================================

@app.get("/")
async def root():
    """服务状态"""
    cfg = get_config()
    return {
        "service": "节能阀 Cost Valve",
        "version": app.version,
        "status": "running",
        "description": "AI API 成本优化中间件",
        "api_base": "/v1",
        "features": {
            "exact_cache": cfg.cache_enabled,
            "prefix_optimization": True,
            "prompt_optimization": cfg.prompt_optimize_enabled,
        },
        "providers": list(cfg.providers.keys()),
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "timestamp": time.time()}


# ============================================================
# 用量统计
# ============================================================

@app.get("/v1/usage")
async def api_usage(_: bool = Depends(verify_api_key), days: int = 30):
    """获取用量统计"""
    try:
        dashboard = get_usage_dashboard(days=days)
        return JSONResponse(content=dashboard)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================
# 模型列表
# ============================================================

@app.get("/v1/models")
async def api_models(_: bool = Depends(verify_api_key)):
    """列出可用模型（OpenAI 兼容格式）"""
    try:
        providers = registry.get_all()
        models = []
        for name, adapter in providers.items():
            for model_name in adapter.config.models:
                models.append({
                    "id": model_name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": name,
                })
        return JSONResponse(content={"object": "list", "data": models})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    import uvicorn
    cfg = get_config()
    uvicorn.run(
        "main:app",
        host=cfg.host,
        port=cfg.port,
        reload=cfg.debug,
        log_level="info",
    )
