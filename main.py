"""
AI Cost Optimizer - FastAPI Entry Point
OpenAI 兼容 API 代理，帮用户节省 50-90% API 成本
"""
import sys
import os
import logging
import time
import re
import ipaddress
from collections import defaultdict
from contextlib import asynccontextmanager
from urllib.parse import urlparse

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

# ============================================================
# 安全配置
# ============================================================

# S1: 管理员密码 - 禁止硬编码默认值，必须通过环境变量设置
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    logging.warning("⚠️ ADMIN_PASSWORD 未设置，管理员接口将拒绝所有请求")

# 服务基础地址
BASE_URL = os.getenv("BASE_URL", "https://costvalve.cloud")

# ============================================================
# SSRF 防护 (S2)
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
        # 白名单域名放行
        if hostname in ALLOWED_UPSTREAM_DOMAINS:
            return True
        # 未知公网域名也放行（允许用户对接新厂商），但内网已拦截
        return True
    except Exception:
        return False

# ============================================================
# 速率限制 (S3) - 轻量内存实现
# ============================================================
_rate_limit_store = defaultdict(list)
_rate_limit_lock_time = [0.0]

RATE_LIMIT_CLEAN_INTERVAL = 300  # 5分钟清理一次过期记录

def check_rate_limit(key: str, limit: int, window: int) -> bool:
    """检查速率限制。返回 True=超限应拒绝, False=正常放行"""
    now = time.time()
    # 定期清理过期记录
    if now - _rate_limit_lock_time[0] > RATE_LIMIT_CLEAN_INTERVAL:
        expired = [k for k, v in _rate_limit_store.items()
                   if not v or v[-1] < now - window * 2]
        for k in expired:
            del _rate_limit_store[k]
        _rate_limit_lock_time[0] = now
    # 清理该 key 的过期记录
    _rate_limit_store[key] = [t for t in _rate_limit_store[key] if t > now - window]
    if len(_rate_limit_store[key]) >= limit:
        return True
    _rate_limit_store[key].append(now)
    return False

# 速率限制配置
RATE_LIMIT_REGISTER = (5, 60)       # 注册: 5次/分钟
RATE_LIMIT_RECOVER = (5, 60)        # 找回: 5次/分钟
RATE_LIMIT_CHAT = (120, 60)         # API调用: 120次/分钟

# ============================================================
# 输入清洗 (W3)
# ============================================================
def sanitize_input(text: str) -> str:
    """移除 HTML 标签和危险字符"""
    text = re.sub(r'<[^>]*>', '', text)
    text = re.sub(r'["\'<>]', '', text)
    return text.strip()

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
    logger.info(f"  Admin password: {'✅ configured' if ADMIN_PASSWORD else '❌ not set'}")
    logger.info("=" * 60)

    # 初始化数据库
    db = init_db(cfg.db_path)

    # 初始化动态定价数据
    try:
        from core.pricing_dynamic import ensure_pricing_file
        ensure_pricing_file()
    except Exception as e:
        logger.warning(f"动态定价初始化失败: {e}")

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
# W1: 生产环境禁用 Swagger/OpenAPI
cfg = get_config()
app = FastAPI(
    title="AI Cost Optimizer",
    description="OpenAI 兼容 API 代理，自动优化 AI API 调用成本",
    version="1.0.0-mvp",
    lifespan=lifespan,
    docs_url="/docs" if cfg.debug else None,
    redoc_url=None,
    openapi_url="/openapi.json" if cfg.debug else None,
)

# S6: CORS 修复 - 指定允许的域名，不再使用 *
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://costvalve.cloud",
        "https://panel.costvalve.cloud",
        "https://api.costvalve.cloud",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Upstream-Key", "X-Upstream-URL"],
)


# ============================================================
# Auth Dependencies
# ============================================================
async def verify_api_key(authorization: str = Header(None)) -> dict:
    """验证 API Key（从 Authorization header）"""
    if not authorization:
        raise HTTPException(status_code=401, detail={
            "error": {"message": "Missing Authorization header", "type": "auth_error"}
        })

    key = authorization
    if key.startswith("Bearer "):
        key = key[7:]

    key_info = authenticate(key)
    if not key_info:
        raise HTTPException(status_code=401, detail={
            "error": {"message": "Invalid API key", "type": "auth_error"}
        })

    return key_info


async def verify_admin(request: Request):
    """验证管理员密码（从 request body 的 password 字段）"""
    try:
        body = await request.json()
        password = body.get("password", "")
    except Exception:
        raise HTTPException(status_code=403, detail={"error": "管理员认证失败"})

    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail={"error": "管理员未配置"})
    if password != ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail={"error": "管理员密码错误"})
    return body


# ============================================================
# 核心 API 端点 (OpenAI 兼容)
# ============================================================

@app.post("/v1/chat/completions")
async def chat_completions(request: Request, body: ChatCompletionRequest,
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
    # S3: 速率限制
    client_ip = request.client.host if request.client else "unknown"
    if check_rate_limit(f"chat:{client_ip}", *RATE_LIMIT_CHAT):
        return JSONResponse(status_code=429, content={
            "error": {"message": "请求过于频繁，请稍后再试", "type": "rate_limit_exceeded"}
        })

    # 必须带上游密钥
    if not x_upstream_key:
        return JSONResponse(status_code=400, content={
            "error": {"message": "Missing X-Upstream-Key header. Please provide your upstream API key.", "type": "missing_upstream_key"}
        })

    # S2: SSRF 防护 - 校验上游 URL
    upstream_url = x_upstream_url or "https://api.deepseek.com"
    if not validate_upstream_url(upstream_url):
        return JSONResponse(status_code=400, content={
            "error": {"message": "Invalid X-Upstream-URL. Private IPs and non-HTTP schemes are not allowed.", "type": "invalid_upstream_url"}
        })

    upstream_adapter = ProviderAdapter(ProviderConfig(
        name="user-upstream",
        base_url=upstream_url,
        api_key=x_upstream_key,
        model=body.model or "deepseek-chat",
        is_mock=False,
    ))

    try:
        if body.stream:
            return await process_stream_chat_completion(body, api_key_info, upstream_adapter=upstream_adapter)
        else:
            return await process_chat_completion(body, api_key_info, upstream_adapter=upstream_adapter)
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
        "api_base": "/v1",
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "timestamp": time.time()}


# S5: API Key 创建 - 需要认证（API Key 或管理员密码）
@app.post("/v1/api-keys")
async def api_create_key(request: Request,
                         authorization: str = Header(None)):
    """创建新的 API Key（需要认证）"""
    # 先尝试 API Key 认证
    authenticated = False
    if authorization:
        key = authorization
        if key.startswith("Bearer "):
            key = key[7:]
        key_info = authenticate(key)
        if key_info:
            authenticated = True

    # 再尝试管理员密码认证
    if not authenticated:
        try:
            body = await request.json()
            password = body.get("password", "")
            if ADMIN_PASSWORD and password == ADMIN_PASSWORD:
                authenticated = True
        except Exception:
            pass

    if not authenticated:
        return JSONResponse(status_code=401, content={
            "error": {"message": "需要 API Key 或管理员密码", "type": "auth_error"}
        })

    try:
        body = await request.json() if request.headers.get("content-type") else {}
    except Exception:
        body = {}

    name = sanitize_input(body.get("name", ""))
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
    """获取缓存节省详情"""
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


# W6: Provider 信息 - 隐藏 is_mock 状态
@app.get("/v1/providers")
async def api_providers(api_key_info: dict = Depends(verify_api_key)):
    """获取已注册的提供商列表（需要认证）"""
    try:
        providers = registry.get_all()
        result = {}
        for name, adapter in providers.items():
            result[name] = {
                "name": adapter.name,
                "default_model": adapter.default_model,
                "models": adapter.config.models,
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
# 用户面板 & 管理接口
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
    """获取账户信息"""
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
    """更新用户设置"""
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
async def api_admin_recharge(body: dict = Depends(verify_admin)):
    """管理员充值接口（需要管理员密码）"""
    try:
        api_key_raw = body.get("api_key", "")
        amount = float(body.get("amount", 0))
        if amount <= 0:
            return JSONResponse(status_code=400, content={"error": "充值金额必须大于0"})

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
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# S4: Admin 接口 - 需要管理员认证
@app.post("/api/admin/license")
async def api_admin_license(request: Request):
    """查看许可证状态（需要管理员密码）"""
    try:
        body = await request.json()
        password = body.get("password", "")
        if not ADMIN_PASSWORD or password != ADMIN_PASSWORD:
            return JSONResponse(status_code=403, content={"error": "管理员密码错误"})

        info = get_license_info()
        return JSONResponse(content=info)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ============================================================
# 注册 & 找回 & 绑定邮箱
# ============================================================

# S3: 注册接口加速率限制
# W3: 输入清洗
@app.post("/api/register")
async def api_register(request: Request):
    """
    开放注册：传入 email 即可自动创建 API Key，Key 通过邮件发送。
    如果邮箱已注册，直接重新发送原 Key。
    """
    # S3: 速率限制
    client_ip = request.client.host if request.client else "unknown"
    if check_rate_limit(f"register:{client_ip}", *RATE_LIMIT_REGISTER):
        return JSONResponse(status_code=429, content={
            "error": {"message": "请求过于频繁，请稍后再试", "type": "rate_limit_exceeded"}
        })

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "无效的 JSON"})

    email = sanitize_input(body.get("email", ""))
    name = sanitize_input(body.get("name", ""))
    if not email or "@" not in email:
        return JSONResponse(status_code=400, content={"error": "请提供有效的邮箱地址"})

    db = get_db()

    # 检查是否已注册
    existing = db.find_key_by_contact(email)
    if existing:
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


# S3: 找回接口加速率限制
@app.post("/api/recover")
async def api_recover(request: Request):
    """通过邮箱找回 API Key"""
    # S3: 速率限制
    client_ip = request.client.host if request.client else "unknown"
    if check_rate_limit(f"recover:{client_ip}", *RATE_LIMIT_RECOVER):
        return JSONResponse(status_code=429, content={
            "error": {"message": "请求过于频繁，请稍后再试", "type": "rate_limit_exceeded"}
        })

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "无效的 JSON"})

    email = sanitize_input(body.get("email", ""))
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
    """为已有 API Key 绑定/更换邮箱"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "无效的 JSON"})

    email = sanitize_input(body.get("email", ""))
    if not email or "@" not in email:
        return JSONResponse(status_code=400, content={"error": "请提供有效的邮箱地址"})

    db = get_db()
    db.update_contact(api_key_info["key_id"], email)

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
                monthly_quota=10000,
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

# ============================================================
# 动态定价接口
# ============================================================

@app.get("/v1/pricing")
async def get_pricing_info():
    """获取所有供应商定价信息（公开接口）"""
    from core.pricing_dynamic import get_pricing, get_all_pricing_summary
    data = get_pricing()
    return {
        "version": data.get("version", "unknown"),
        "updated_at": data.get("updated_at", ""),
        "providers": get_all_pricing_summary(),
        "detail": {k: {
            "name": v.get("name"),
            "has_peak_valley": v.get("has_peak_valley"),
            "peak_hours": v.get("peak_hours"),
            "peak_multiplier": v.get("peak_multiplier"),
            "models": v.get("models")
        } for k, v in data.get("providers", {}).items()}
    }

@app.get("/v1/schedule")
async def get_schedule_status(provider: str = "deepseek", api_key_info: dict = Depends(verify_api_key)):
    """获取当前调度状态（需认证）"""
    from core.pricing_dynamic import get_scheduling_status, is_peak_time, get_next_offpeak
    status = get_scheduling_status(provider)
    return status

@app.post("/api/admin/pricing")
async def update_pricing(request: Request):
    """更新供应商定价（需管理员认证）"""
    # 验证管理员密码
    body = await request.json()
    password = body.get("password", "")
    if password != ADMIN_PASSWORD or not ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="管理员认证失败")
    
    provider = body.get("provider")
    pricing_data = body.get("pricing")
    if not provider or not pricing_data:
        raise HTTPException(status_code=400, detail="缺少 provider 或 pricing 参数")
    
    from core.pricing_dynamic import update_provider_pricing, reload_pricing
    success = update_provider_pricing(provider, pricing_data)
    if success:
        reload_pricing()
        return {"status": "ok", "message": f"供应商 {provider} 定价已更新"}
    raise HTTPException(status_code=500, detail="定价更新失败")


# ==================== Admin: 全局用量统计 ====================
@app.get("/api/admin/stats")
async def admin_stats(x_admin_key: str = Header(default="")):
    """管理员全局用量统计 - 每日调用量、收入、模型分布"""
    if x_admin_key != ADMIN_PASSWORD:
        return JSONResponse(status_code=401, content={"error": "管理员认证失败"})
    
    try:
        import sqlite3
        from datetime import datetime, timedelta
        
        db_path = os.path.join(os.path.dirname(__file__), "data", "ai_cost_optimizer.db")
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        # 今日统计
        cur.execute("""
            SELECT COUNT(*), 
                   COALESCE(SUM(total_tokens), 0),
                   COALESCE(SUM(actual_cost), 0),
                   COALESCE(SUM(proxy_fee), 0),
                   COALESCE(SUM(saved_cost), 0)
            FROM usage_records 
            WHERE created_at LIKE ?
        """, (f"{today}%",))
        today_stats = cur.fetchone()
        
        # 昨日统计
        cur.execute("""
            SELECT COUNT(*), 
                   COALESCE(SUM(total_tokens), 0),
                   COALESCE(SUM(actual_cost), 0),
                   COALESCE(SUM(proxy_fee), 0),
                   COALESCE(SUM(saved_cost), 0)
            FROM usage_records 
            WHERE created_at LIKE ?
        """, (f"{yesterday}%",))
        yesterday_stats = cur.fetchone()
        
        # 总计统计
        cur.execute("""
            SELECT COUNT(*), 
                   COALESCE(SUM(total_tokens), 0),
                   COALESCE(SUM(actual_cost), 0),
                   COALESCE(SUM(proxy_fee), 0),
                   COALESCE(SUM(saved_cost), 0)
            FROM usage_records
        """)
        total_stats = cur.fetchone()
        
        # 模型使用分布
        cur.execute("""
            SELECT model, COUNT(*), COALESCE(SUM(total_tokens), 0), 
                   COALESCE(SUM(actual_cost), 0), COALESCE(SUM(proxy_fee), 0)
            FROM usage_records
            GROUP BY model
            ORDER BY COUNT(*) DESC
        """)
        model_stats = [{"model": r[0], "calls": r[1], "tokens": r[2], "cost": round(r[3], 6), "revenue": round(r[4], 6)} for r in cur.fetchall()]
        
        # 供应商分布
        cur.execute("""
            SELECT provider, COUNT(*), COALESCE(SUM(total_tokens), 0),
                   COALESCE(SUM(actual_cost), 0)
            FROM usage_records
            GROUP BY provider
            ORDER BY COUNT(*) DESC
        """)
        provider_stats = [{"provider": r[0], "calls": r[1], "tokens": r[2], "cost": round(r[3], 6)} for r in cur.fetchall()]
        
        # API Keys 统计
        cur.execute("SELECT COUNT(*) FROM api_keys WHERE is_active = 1")
        active_keys = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM api_keys WHERE used_this_month > 0")
        keys_with_usage = cur.fetchone()[0]
        
        # 近7天趋势
        cur.execute("""
            SELECT substr(created_at, 1, 10) as day, 
                   COUNT(*), COALESCE(SUM(total_tokens), 0),
                   COALESCE(SUM(actual_cost), 0), COALESCE(SUM(proxy_fee), 0)
            FROM usage_records
            WHERE created_at >= date("now", "-7 days")
            GROUP BY day
            ORDER BY day
        """)
        daily_trend = [{"date": r[0], "calls": r[1], "tokens": r[2], "cost": round(r[3], 6), "revenue": round(r[4], 6)} for r in cur.fetchall()]
        
        conn.close()
        
        return JSONResponse(content={
            "date": today,
            "today": {
                "calls": today_stats[0],
                "tokens": today_stats[1],
                "cost": round(today_stats[2], 6),
                "revenue": round(today_stats[3], 6),
                "saved": round(today_stats[4], 6)
            },
            "yesterday": {
                "calls": yesterday_stats[0],
                "tokens": yesterday_stats[1],
                "cost": round(yesterday_stats[2], 6),
                "revenue": round(yesterday_stats[3], 6),
                "saved": round(yesterday_stats[4], 6)
            },
            "total": {
                "calls": total_stats[0],
                "tokens": total_stats[1],
                "cost": round(total_stats[2], 6),
                "revenue": round(total_stats[3], 6),
                "saved": round(total_stats[4], 6)
            },
            "active_keys": active_keys,
            "keys_with_usage": keys_with_usage,
            "model_stats": model_stats,
            "provider_stats": provider_stats,
            "daily_trend": daily_trend
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
