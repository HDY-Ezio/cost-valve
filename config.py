"""
AI Cost Optimizer - Configuration
全局配置管理，支持环境变量覆盖
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DeepSeekPricing:
    """DeepSeek 峰谷定价配置（2026年7月中旬生效）"""
    # 正常价格（每百万 tokens）
    input_normal: float = 3.0
    output_normal: float = 6.0
    cache_hit_normal: float = 0.025

    # 高峰价格（每百万 tokens）
    input_peak: float = 6.0
    output_peak: float = 12.0
    cache_hit_peak: float = 0.05

    # 高峰时段（北京时间 24h 格式）
    peak_hours: List[tuple] = field(default_factory=lambda: [
        (9, 12),   # 9:00 - 12:00
        (14, 18),  # 14:00 - 18:00
    ])


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
    mock_mode: bool = os.getenv("MOCK_MODE", "true").lower() == "true"

    # 数据库
    db_path: str = os.getenv("DB_PATH", "./data/ai_cost_optimizer.db")

    # 默认 LLM 提供商
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)

    # 计费配置
    free_quota_monthly: int = 1000
    price_per_call: float = 0.01  # 0.01元/次

    # 调度配置
    scheduler_check_interval: int = 60
    task_max_wait_hours: int = 12

    # 缓存配置
    cache_enabled: bool = True
    exact_cache_ttl: int = 3600
    semantic_cache_ttl: int = 86400
    semantic_threshold: float = 0.95
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    embedding_dim: int = 1536

    # 预算配置
    default_monthly_budget: float = 100.0  # 默认月度预算100元
    budget_warn_threshold: float = 0.8     # 80%时告警
    budget_degrade_threshold: float = 0.95 # 95%时降级

    # Prompt瘦身配置
    prompt_optimize_enabled: bool = True
    prompt_max_tokens: int = 4096

    # 智能路由配置
    router_enabled: bool = True
    simple_model: str = "deepseek-chat"
    complex_model: str = "deepseek-reasoner"

    def __post_init__(self):
        self._load_providers()

    def _load_providers(self):
        """从环境变量加载提供商配置"""
        # DeepSeek
        ds_key = os.getenv("DEEPSEEK_API_KEY", "")
        if ds_key or self.mock_mode:
            self.providers["deepseek"] = ProviderConfig(
                name="deepseek",
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                api_key=ds_key or "mock-key",
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                models=["deepseek-chat", "deepseek-reasoner"],
                is_mock=self.mock_mode,
            )
        # 阿里云百炼
        aliyun_key = os.getenv("ALIYUN_API_KEY", "")
        if aliyun_key or self.mock_mode:
            self.providers["aliyun"] = ProviderConfig(
                name="aliyun",
                base_url=os.getenv("ALIYUN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode"),
                api_key=aliyun_key or "mock-key",
                model=os.getenv("ALIYUN_MODEL", "qwen-turbo"),
                models=["qwen-turbo", "qwen-plus", "qwen-max"],
                is_mock=self.mock_mode,
            )
        # 通用 OpenAI 兼容提供商（可自由添加）
        generic_key = os.getenv("GENERIC_API_KEY", "")
        generic_url = os.getenv("GENERIC_BASE_URL", "")
        if generic_key and generic_url:
            self.providers["generic"] = ProviderConfig(
                name="generic",
                base_url=generic_url,
                api_key=generic_key,
                model=os.getenv("GENERIC_MODEL", "gpt-4o-mini"),
                models=os.getenv("GENERIC_MODELS", "gpt-4o-mini,gpt-4o").split(","),
                is_mock=self.mock_mode,
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
