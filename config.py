"""
节能阀 Cost Valve - 配置管理
AI API 成本优化中间件 - 开源版
支持环境变量覆盖
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ProviderConfig:
    """LLM 提供商配置"""
    name: str
    base_url: str
    api_key: str
    model: str
    models: List[str] = field(default_factory=list)
    max_retries: int = 3
    timeout: int = 120
    is_mock: bool = False


@dataclass
class AppConfig:
    """应用全局配置"""
    # 服务配置
    host: str = os.getenv("APP_HOST", "0.0.0.0")
    port: int = int(os.getenv("APP_PORT", "8000"))
    debug: bool = os.getenv("APP_DEBUG", "false").lower() == "true"

    # 数据库
    db_path: str = os.getenv("DB_PATH", "./data/cost_valve.db")

    # 默认 LLM 提供商
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)

    # 缓存配置
    cache_enabled: bool = os.getenv("CACHE_ENABLED", "true").lower() == "true"
    exact_cache_ttl: int = int(os.getenv("EXACT_CACHE_TTL", "3600"))  # 1小时

    # API Key 配置
    # 单用户模式：设置此环境变量即可使用，无需注册
    api_key: str = os.getenv("COST_VALVE_API_KEY", "")

    # Prompt瘦身配置
    prompt_optimize_enabled: bool = os.getenv("PROMPT_OPTIMIZE_ENABLED", "true").lower() == "true"
    prompt_max_tokens: int = int(os.getenv("PROMPT_MAX_TOKENS", "4096"))

    def __post_init__(self):
        self._load_providers()
        # 如果没有设置 API Key，自动生成一个默认的
        if not self.api_key:
            import uuid
            self.api_key = f"cv-{uuid.uuid4().hex[:16]}"

    def _load_providers(self):
        """从环境变量加载提供商配置"""
        # DeepSeek
        ds_key = os.getenv("DEEPSEEK_API_KEY", "")
        if ds_key:
            self.providers["deepseek"] = ProviderConfig(
                name="deepseek",
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                api_key=ds_key,
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                models=["deepseek-chat", "deepseek-reasoner"],
                is_mock=False,
            )
        # 阿里云百炼
        aliyun_key = os.getenv("ALIYUN_API_KEY", "")
        if aliyun_key:
            self.providers["aliyun"] = ProviderConfig(
                name="aliyun",
                base_url=os.getenv("ALIYUN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode"),
                api_key=aliyun_key,
                model=os.getenv("ALIYUN_MODEL", "qwen-turbo"),
                models=["qwen-turbo", "qwen-plus", "qwen-max"],
                is_mock=False,
            )
        # 豆包（字节跳动/火山引擎）
        doubao_key = os.getenv("DOUBAO_API_KEY", "")
        if doubao_key:
            self.providers["doubao"] = ProviderConfig(
                name="doubao",
                base_url=os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
                api_key=doubao_key,
                model=os.getenv("DOUBAO_MODEL", "doubao-pro-32k"),
                models=["doubao-pro-32k", "doubao-pro-128k", "doubao-lite-32k"],
                is_mock=False,
            )
        # Anthropic Claude
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            self.providers["anthropic"] = ProviderConfig(
                name="anthropic",
                base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
                api_key=anthropic_key,
                model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                models=["claude-opus-4-20250514", "claude-sonnet-4-20250514", "claude-haiku-4-20250514"],
                is_mock=False,
            )
        # Google Gemini
        google_key = os.getenv("GOOGLE_API_KEY", "")
        if google_key:
            self.providers["google"] = ProviderConfig(
                name="google",
                base_url=os.getenv("GOOGLE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"),
                api_key=google_key,
                model=os.getenv("GOOGLE_MODEL", "gemini-3-flash"),
                models=["gemini-3.1-pro", "gemini-3.5-flash", "gemini-3-flash", "gemini-3.1-flash-lite"],
                is_mock=False,
            )
        # OpenAI
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if openai_key:
            self.providers["openai"] = ProviderConfig(
                name="openai",
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_key=openai_key,
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                models=["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
                is_mock=False,
            )
        # 智谱 GLM
        glm_key = os.getenv("GLM_API_KEY", "")
        if glm_key:
            self.providers["glm"] = ProviderConfig(
                name="glm",
                base_url=os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
                api_key=glm_key,
                model=os.getenv("GLM_MODEL", "glm-4"),
                models=["glm-4", "glm-4-flash", "glm-3-turbo"],
                is_mock=False,
            )
        # 通用 OpenAI 兼容提供商
        generic_key = os.getenv("GENERIC_API_KEY", "")
        generic_url = os.getenv("GENERIC_BASE_URL", "")
        if generic_key and generic_url:
            self.providers["generic"] = ProviderConfig(
                name="generic",
                base_url=generic_url,
                api_key=generic_key,
                model=os.getenv("GENERIC_MODEL", "gpt-4o-mini"),
                models=os.getenv("GENERIC_MODELS", "gpt-4o-mini,gpt-4o").split(","),
                is_mock=False,
            )


# 全局配置单例
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig()
    return _config


def reset_config():
    """重置配置（测试用）"""
    global _config
    _config = None
