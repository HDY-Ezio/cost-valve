"""
AI Cost Optimizer - FastAPI Entry Point
OpenAI 兼容 API 代理，帮用户节省 50-90% API 成本
"""
import sys
import os
import logging
import time
from contextlib import asynccontextmanager

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request, Depends, HTTPException, Header
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from config import get_config
from models import ChatCompletionRequest, generate_request_id
from core.auth import authenticate, create_key, hash_api_key
from core.proxy import process_chat_completion, process_stream_chat_completion
from core.savings import get_savings_dashboard
from core.providers import registry, ProviderAdapter
from config import ProviderConfig
from core.scheduler import get_scheduling_info
from core.usage import get_dashboard
from core.budget import check_budget, check_quota
from core.license import validate_license, get_license_info
from db.database import init_db, get_db
from email_sender import init as init_resend, send_api_key_email

# 管理员密码（环境变量覆盖）
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "xingmu2026")

# 服务基础地址（环境变量覆盖，避免硬编码IP）
BASE_URL = os.getenv("BASE_URL", "http://154.8.211.17/gateway")

# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ai-cost-optimizer")


# ============================================================
# Lifespan
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时的操作"""
    # 许可证验证（最先执行）
    if not validate_license():
        logger.critical("🚫 许可证验证失败，服务拒绝启动！")
        raise RuntimeError("许可证验证失败，请检查 LICENSE_KEY 环境变量")

    # 启动
    cfg = get_config()
    logger.info("=" * 60)
    logger.info("  节能阀 AI Cost Optimizer - Starting up")
    logger.info(f"  Mock mode: {cfg.mock_mode}")
    logger.info(f"  Providers: {list(cfg.providers.keys())}")
    logger.info(f"  Free quota: {cfg.free_quota_monthly}/month")
    logger.info(f"  Price per call: ¥{cfg.price_per_call}")
    logger.info(f"  Base URL: {BASE_URL}")
    logger.info("=" * 60)

    # 初始化数据库
    db = init_db(cfg.db_path)

    # 初始化邮件服务
    init_resend()

    # 初始化提供商注册中心
    registry.initialize()

    # 创建默认 API Key（如果不存在）
    _ensure_default_key()

    yield

    # 关闭
    logger.info("AI Cost Optimizer - Shutting down")


# ============================================================
# FastAPI App
# ============================================================
app = FastAPI(
    title="AI Cost Optimizer",
    description="OpenAI 兼容 API 代理，自动优化 AI API 调用成本",
    version="1.0.0-mvp",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Auth Dependency
# ============================================================
async def verify_api_key(authorization: str = Header(None)) -> dict:
    """验证 API Key（从 Authorization header）"""
    if not authorization:
        raise HTTPException(status_code=401, detail={
            "error": {"message": "Missing Authorization header", "type": "auth_error"}
        })

    # 支持 "Bearer sk-xxx" 和 "sk-xxx" 两种格式
    key = authorization
    if key.startswith("Bearer "):
        key = key[7:]

    key_info = authenticate(key)
    if not key_info:
        raise HTTPException(status_code=401, detail={
            "error": {"message": "Invalid API key", "type": "auth_error"}
        })

    return key_info


# ============================================================
# 核心 API 端点 (OpenAI 兼容)
# ============================================================

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest,
                           api_key_info: dict = Depends(verify_api_key),
                           x_upstream_key: str = Header(None, alias="X-Upstream-Key"),
                           x_upstream_url: str = Header(None, alias="X-Upstream-URL")):
    """
    Chat Completions API (OpenAI 兼容)
    支持流式和非流式
    可选 Header：
      X-Upstream-Key：用户自己的上游 API 密钥（有则用用户的，无则走服务端默认）
      X-Upstream-URL：用户指定的上游厂商地址（配合 X-Upstream-Key 使用）
    """
    # 必须带上游密钥，否则拒绝——阀门不替人付费
    if not x_upstream_key:
        return JSONResponse(status_code=400, content={
            "error": {"message": "Missing X-Upstream-Key header. Please provide your upstream API key.", "type": "missing_upstream_key"}
        })
    upstream_url = x_upstream_url or "https://api.deepseek.com"
    upstream_adapter = ProviderAdapter(ProviderConfig(
        name="user-upstream",
        base_url=upstream_url,
        api_key=x_upstream_key,
        model=request.model or "deepseek-chat",
        is_mock=False,
    ))

    try:
        if request.stream:
            return await process_stream_chat_completion(request, api_key_info, upstream_adapter=upstream_adapter)
        else:
            return await process_chat_completion(request, api_key_info, upstream_adapter=upstream_adapter)
    except HTTPException:
        raise
    except Exception as e:
        logger.critical(f"Unhandled exception in /v1/chat/completions: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Internal server error", "type": "internal_error"}}
        )


# ============================================================
# 管理 API 端点
# ============================================================

@app.get("/")
async def root():
    """服务状态"""
    return {
        "service": "AI Cost Optimizer",
        "version": "1.0.0-mvp",
        "status": "running",
        "docs": "/docs",
        "api_base": "/v1",
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "timestamp": time.time()}


@app.post("/v1/api-keys")
async def api_create_key(request: Request):
    """创建新的 API Key"""
    try:
        body = await request.json() if request.headers.get("content-type") else {}
    except Exception:
        body = {}

    name = body.get("name", "")
    monthly_quota = body.get("monthly_quota", 1000)
    monthly_budget = body.get("monthly_budget", 100.0)

    try:
        result = create_key(name, monthly_quota, monthly_budget)
        return JSONResponse(content={
            "message": "API key created successfully",
            "data": result,
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/v1/usage")
async def api_usage(api_key_info: dict = Depends(verify_api_key)):
    """获取用量 Dashboard"""
    try:
        dashboard = get_dashboard(api_key_info["key_id"])
        return JSONResponse(content=dashboard)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/v1/savings")
async def api_savings(api_key_info: dict = Depends(verify_api_key)):
    """获取缓存节省详情：上游缓存命中、前缀优化、网关缓存节省明细"""
    try:
        dashboard = get_savings_dashboard(api_key_info["key_id"])
        return JSONResponse(content=dashboard)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/v1/budget")
async def api_budget(api_key_info: dict = Depends(verify_api_key)):
    """获取预算状态"""
    try:
        action, status = check_budget(api_key_info["key_id"])
        return JSONResponse(content={"action": action, "status": status})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/v1/schedule/info")
async def api_schedule_info():
    """获取当前调度信息（峰谷状态）"""
    try:
        info = get_scheduling_info()
        return JSONResponse(content=info)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/v1/providers")
async def api_providers():
    """获取已注册的提供商列表"""
    try:
        providers = registry.get_all()
        result = {}
        for name, adapter in providers.items():
            result[name] = {
                "name": adapter.name,
                "base_url": adapter.base_url,
                "default_model": adapter.default_model,
                "models": adapter.config.models,
                "is_mock": adapter.is_mock,
            }
        return JSONResponse(content={"providers": result})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/v1/models")
async def api_models(api_key_info: dict = Depends(verify_api_key)):
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
            if adapter.default_model not in [m["id"] for m in models]:
                models.append({
                    "id": adapter.default_model,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": name,
                })
        return JSONResponse(content={"object": "list", "data": models})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================
# 用户面板 & 充值接口
# ============================================================

PORTAL_HTML_PATH = os.path.join(os.path.dirname(__file__), "static", "portal.html")


@app.get("/portal")
async def portal_page():
    """用户面板页面"""
    if os.path.exists(PORTAL_HTML_PATH):
        return FileResponse(PORTAL_HTML_PATH, media_type="text/html")
    return HTMLResponse("<h1>Portal not found</h1>", status_code=404)


@app.get("/api/account")
async def api_account(api_key_info: dict = Depends(verify_api_key)):
    """获取账户信息：余额、用量、提醒设置"""
    try:
        db = get_db()
        cfg = get_config()
        key_id = api_key_info["key_id"]

        summary = db.get_usage_summary(key_id, days=30)
        balance = db.get_balance(key_id)

        return JSONResponse(content={
            "key_id": key_id,
            "name": api_key_info.get("name", ""),
            "balance": round(balance, 2),
            "monthly_quota": api_key_info.get("monthly_quota", cfg.free_quota_monthly),
            "calls_used": api_key_info.get("used_this_month", 0),
            "calls_today": summary.get("calls_today", 0),
            "cache_hit_rate": round(
                (summary.get("cache_hits", 0) / summary.get("total_calls", 1) * 100)
                if summary.get("total_calls", 0) > 0 else 0, 1
            ),
            "total_saved": round(summary.get("total_saved", 0), 4),
            "alert_threshold": api_key_info.get("alert_threshold", 0),
            "price_per_call": cfg.price_per_call,
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.put("/api/settings")
async def api_settings(request: Request, api_key_info: dict = Depends(verify_api_key)):
    """更新用户设置（提醒阈值等）"""
    try:
        body = await request.json()
        key_id = api_key_info["key_id"]
        db = get_db()

        if "alert_threshold" in body:
            threshold = int(body["alert_threshold"])
            if threshold < 0:
                return JSONResponse(status_code=400, content={"error": "阈值不能为负数"})
            db.set_alert_threshold(key_id, threshold)

        return JSONResponse(content={"message": "设置已更新"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/admin/recharge")
async def api_admin_recharge(request: Request):
    """管理员充值接口"""
    try:
        body = await request.json()
        password = body.get("password", "")
        if password != ADMIN_PASSWORD:
            return JSONResponse(status_code=403, content={"error": "管理员密码错误"})

        api_key_raw = body.get("api_key", "")
        amount = float(body.get("amount", 0))
        if amount <= 0:
            return JSONResponse(status_code=400, content={"error": "充值金额必须大于0"})

        # 通过 API key 原文找到 key_id
        key_hash = hash_api_key(api_key_raw)
        db = get_db()
        key_info = db.get_api_key(key_hash)
        if not key_info:
            return JSONResponse(status_code=404, content={"error": "API Key 不存在"})

        db.add_balance(key_info["key_id"], amount)
        new_balance = db.get_balance(key_info["key_id"])

        return JSONResponse(content={
            "message": f"充值成功：+{amount:.2f}元",
            "new_balance": round(new_balance, 2),
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/admin/license")
async def api_admin_license():
    """查看许可证状态"""
    try:
        info = get_license_info()
        return JSONResponse(content=info)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================
# 注册 & 找回 & 绑定邮箱
# ============================================================

@app.post("/api/register")
async def api_register(request: Request):
    """
    开放注册：传入 email 即可自动创建 API Key，Key 通过邮件发送。
    如果邮箱已注册，直接重新发送原 Key。
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "无效的 JSON"})

    email = body.get("email", "").strip()
    name = body.get("name", "").strip()
    if not email or "@" not in email:
        return JSONResponse(status_code=400, content={"error": "请提供有效的邮箱地址"})

    db = get_db()

    # 检查是否已注册
    existing = db.find_key_by_contact(email)
    if existing:
        # 已注册，重新发送 Key
        raw_key = existing.get("raw_key", "")
        if not raw_key:
            return JSONResponse(status_code=500, content={"error": "该账户未存储密钥，请联系管理员"})
        sent = send_api_key_email(email, raw_key, f"{BASE_URL}/portal")
        if sent:
            return JSONResponse(content={
                "message": "您已注册过，API Key 已重新发送到您的邮箱",
                "email": email,
            })
        else:
            return JSONResponse(status_code=500, content={"error": "邮件发送失败，请稍后重试"})

    # 新注册
    try:
        result = create_key(name=name, contact=email)
        raw_key = result["api_key"]
        # 更新联系方式和原始 Key
        db.update_contact(result["key_id"], email)
        db.update_raw_key(result["key_id"], raw_key)

        sent = send_api_key_email(email, raw_key, f"{BASE_URL}/portal")
        return JSONResponse(content={
            "message": "注册成功！API Key 已发送到您的邮箱",
            "email": email,
        })
    except Exception as e:
        logger.error(f"Register error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/recover")
async def api_recover(request: Request):
    """
    通过邮箱找回 API Key
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "无效的 JSON"})

    email = body.get("email", "").strip()
    if not email or "@" not in email:
        return JSONResponse(status_code=400, content={"error": "请提供有效的邮箱地址"})

    db = get_db()
    key_info = db.find_key_by_contact(email)
    if not key_info:
        return JSONResponse(status_code=404, content={"error": "该邮箱未注册"})

    raw_key = key_info.get("raw_key", "")
    if not raw_key:
        return JSONResponse(status_code=500, content={"error": "该账户未存储密钥，请联系管理员"})

    sent = send_api_key_email(email, raw_key, f"{BASE_URL}/portal")
    if sent:
        return JSONResponse(content={
            "message": "API Key 已发送到您的邮箱",
            "email": email,
        })
    else:
        return JSONResponse(status_code=500, content={"error": "邮件发送失败，请稍后重试"})


@app.post("/api/update-email")
async def api_update_email(request: Request, api_key_info: dict = Depends(verify_api_key)):
    """
    为已有 API Key 绑定/更换邮箱
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "无效的 JSON"})

    email = body.get("email", "").strip()
    if not email or "@" not in email:
        return JSONResponse(status_code=400, content={"error": "请提供有效的邮箱地址"})

    db = get_db()
    db.update_contact(api_key_info["key_id"], email)

    # 如果有 raw_key，顺便发一封确认邮件
    raw_key = api_key_info.get("raw_key", "")
    if raw_key:
        db.update_raw_key(api_key_info["key_id"], raw_key)
        send_api_key_email(email, raw_key, f"{BASE_URL}/portal")

    return JSONResponse(content={
        "message": "邮箱绑定成功",
        "email": email,
    })


# ============================================================
# 默认 API Key 初始化
# ============================================================

def _ensure_default_key():
    """确保至少有一个可用的 API Key（开发/测试用）"""
    try:
        from db.database import get_db
        db = get_db()

        # 从环境变量读取默认Key（生产环境不应使用）
        default_key_raw = os.environ.get("DEFAULT_KEY_RAW", "")
        if not default_key_raw:
            logger.info("未配置 DEFAULT_KEY_RAW，跳过默认Key创建")
            return
            
        key_hash = hash_api_key(default_key_raw)

        key_info = db.get_api_key(key_hash)
        if not key_info:
            import uuid
            db.create_api_key(
                key_id=uuid.uuid4().hex[:16],
                key_hash=key_hash,
                name="Default Dev Key",
                monthly_quota=10000,  # 开发用，给多一些
                monthly_budget=1000.0,
            )
            logger.info(f"Default API key created: {default_key_raw}")
        else:
            logger.info("Default API key already exists")
    except Exception as e:
        logger.error(f"Failed to create default key: {e}")


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
