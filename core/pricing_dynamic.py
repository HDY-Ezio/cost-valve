"""
节能阀 - 动态定价管理
从 JSON 文件加载供应商定价，支持运行时热更新，无需重启
"""
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))

# 定价数据文件路径
PRICING_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "provider_pricing.json")

# 内存缓存
_pricing_cache: Optional[Dict] = None
_cache_loaded_at: Optional[datetime] = None


def _load_pricing_file() -> Dict:
    """从 JSON 文件加载定价数据"""
    global _pricing_cache, _cache_loaded_at
    try:
        with open(PRICING_FILE, "r", encoding="utf-8") as f:
            _pricing_cache = json.load(f)
            _cache_loaded_at = datetime.now(CST)
            logger.info(f"✅ 定价数据已加载: {len(_pricing_cache.get('providers', {}))} 个供应商")
            return _pricing_cache
    except FileNotFoundError:
        logger.warning(f"⚠️ 定价文件不存在: {PRICING_FILE}，使用默认值")
        return _get_default_pricing()
    except json.JSONDecodeError as e:
        logger.error(f"❌ 定价文件格式错误: {e}")
        return _pricing_cache or _get_default_pricing()


def _save_pricing_file(data: Dict) -> bool:
    """保存定价数据到 JSON 文件"""
    try:
        os.makedirs(os.path.dirname(PRICING_FILE), exist_ok=True)
        with open(PRICING_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        global _pricing_cache, _cache_loaded_at
        _pricing_cache = data
        _cache_loaded_at = datetime.now(CST)
        logger.info("✅ 定价数据已保存")
        return True
    except Exception as e:
        logger.error(f"❌ 保存定价数据失败: {e}")
        return False


def _get_default_pricing() -> Dict:
    """默认定价数据（2026年7月最新）"""
    return {
        "version": "2026-07-03",
        "updated_at": "2026-07-03T01:30:00+08:00",
        "providers": {
            "deepseek": {
                "name": "DeepSeek",
                "has_peak_valley": True,
                "peak_hours": [[9, 12], [14, 18]],
                "peak_multiplier": 2.0,
                "currency": "CNY",
                "unit": "元/百万tokens",
                "models": {
                    "deepseek-v4-pro": {
                        "normal": {"input_cache_hit": 0.025, "input_cache_miss": 3.0, "output": 6.0},
                        "peak": {"input_cache_hit": 0.05, "input_cache_miss": 6.0, "output": 12.0}
                    },
                    "deepseek-v4-flash": {
                        "normal": {"input_cache_hit": 0.02, "input_cache_miss": 1.0, "output": 2.0},
                        "peak": {"input_cache_hit": 0.04, "input_cache_miss": 2.0, "output": 4.0}
                    },
                    "deepseek-chat": {
                        "normal": {"input_cache_hit": 0.025, "input_cache_miss": 3.0, "output": 6.0},
                        "peak": {"input_cache_hit": 0.05, "input_cache_miss": 6.0, "output": 12.0}
                    },
                    "deepseek-reasoner": {
                        "normal": {"input_cache_hit": 0.025, "input_cache_miss": 3.0, "output": 6.0},
                        "peak": {"input_cache_hit": 0.05, "input_cache_miss": 6.0, "output": 12.0}
                    }
                }
            },
            "aliyun": {
                "name": "通义千问 (阿里云)",
                "has_peak_valley": False,
                "peak_hours": [],
                "peak_multiplier": 1.0,
                "currency": "CNY",
                "unit": "元/百万tokens",
                "models": {
                    "qwen3.7-max": {
                        "normal": {"input": 2.5, "output": 7.5},
                        "peak": {"input": 2.5, "output": 7.5}
                    },
                    "qwen3.7-plus": {
                        "normal": {"input": 0.4, "output": 1.6},
                        "peak": {"input": 0.4, "output": 1.6}
                    },
                    "qwen3.7-flash": {
                        "normal": {"input": 0.03, "output": 0.06},
                        "peak": {"input": 0.03, "output": 0.06}
                    },
                    "qwen-turbo": {
                        "normal": {"input": 0.03, "output": 0.06},
                        "peak": {"input": 0.03, "output": 0.06}
                    },
                    "qwen-plus": {
                        "normal": {"input": 0.4, "output": 1.6},
                        "peak": {"input": 0.4, "output": 1.6}
                    },
                    "qwen-max": {
                        "normal": {"input": 2.5, "output": 7.5},
                        "peak": {"input": 2.5, "output": 7.5}
                    }
                }
            },
            "doubao": {
                "name": "豆包 (字节跳动)",
                "has_peak_valley": False,
                "peak_hours": [],
                "peak_multiplier": 1.0,
                "currency": "CNY",
                "unit": "元/百万tokens",
                "models": {
                    "doubao-pro-32k": {
                        "normal": {"input": 0.8, "output": 2.0},
                        "peak": {"input": 0.8, "output": 2.0}
                    },
                    "doubao-pro-128k": {
                        "normal": {"input": 5.0, "output": 9.0},
                        "peak": {"input": 5.0, "output": 9.0}
                    },
                    "doubao-lite-32k": {
                        "normal": {"input": 0.3, "output": 0.6},
                        "peak": {"input": 0.3, "output": 0.6}
                    }
                }
            },
            "openai": {
                "name": "OpenAI",
                "has_peak_valley": False,
                "peak_hours": [],
                "peak_multiplier": 1.0,
                "currency": "USD",
                "unit": "USD/百万tokens",
                "models": {
                    "gpt-4o": {
                        "normal": {"input": 2.5, "output": 10.0},
                        "peak": {"input": 2.5, "output": 10.0}
                    },
                    "gpt-4o-mini": {
                        "normal": {"input": 0.15, "output": 0.6},
                        "peak": {"input": 0.15, "output": 0.6}
                    }
                }
            }
        }
    }


def get_pricing() -> Dict:
    """获取当前定价数据（带内存缓存）"""
    global _pricing_cache
    if _pricing_cache is None:
        return _load_pricing_file()
    return _pricing_cache


def reload_pricing() -> Dict:
    """强制重新加载定价数据"""
    global _pricing_cache
    _pricing_cache = None
    return _load_pricing_file()


def get_provider_pricing(provider: str) -> Optional[Dict]:
    """获取指定供应商的定价"""
    data = get_pricing()
    return data.get("providers", {}).get(provider)


def get_model_pricing(provider: str, model: str) -> Optional[Dict]:
    """获取指定供应商指定模型的定价"""
    provider_data = get_provider_pricing(provider)
    if not provider_data:
        return None
    return provider_data.get("models", {}).get(model)


def is_peak_time(provider: str = "deepseek", now: Optional[datetime] = None) -> bool:
    """判断当前是否为某供应商的高峰时段"""
    provider_data = get_provider_pricing(provider)
    if not provider_data or not provider_data.get("has_peak_valley"):
        return False

    if now is None:
        now = datetime.now(CST)

    hour = now.hour
    for start, end in provider_data.get("peak_hours", []):
        if start <= hour < end:
            return True
    return False


def get_next_offpeak(provider: str = "deepseek", from_time: Optional[datetime] = None) -> datetime:
    """计算下一个低峰时段"""
    if from_time is None:
        from_time = datetime.now(CST)

    provider_data = get_provider_pricing(provider)
    if not provider_data or not provider_data.get("has_peak_valley"):
        return from_time  # 无峰谷机制，立即返回

    hour = from_time.hour
    peaks = sorted(provider_data.get("peak_hours", []))

    for start, end in peaks:
        if hour < start:
            return from_time  # 现在就是低峰
        elif start <= hour < end:
            return from_time.replace(hour=end, minute=0, second=0, microsecond=0)

    return from_time  # 最后一个高峰之后，已是低峰


def get_scheduling_status(provider: str = "deepseek") -> Dict[str, Any]:
    """获取当前调度状态（用于 API 返回）"""
    now = datetime.now(CST)
    peak = is_peak_time(provider, now)
    next_offpeak = get_next_offpeak(provider, now)

    provider_data = get_provider_pricing(provider) or {}

    return {
        "provider": provider,
        "provider_name": provider_data.get("name", provider),
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S CST"),
        "has_peak_valley": provider_data.get("has_peak_valley", False),
        "is_peak": peak,
        "peak_multiplier": provider_data.get("peak_multiplier", 1.0),
        "peak_hours": provider_data.get("peak_hours", []),
        "next_offpeak": next_offpeak.strftime("%Y-%m-%d %H:%M CST") if peak and provider_data.get("has_peak_valley") else None,
        "recommendation": _get_recommendation(peak, provider_data.get("has_peak_valley", False))
    }


def _get_recommendation(is_peak: bool, has_pv: bool) -> str:
    """生成调度建议"""
    if not has_pv:
        return "该供应商无峰谷定价，无需调度优化"
    if is_peak:
        return "⚠️ 当前为高峰时段，非紧急任务建议延迟到低峰执行，可节省 50% 费用"
    return "✅ 当前为低峰时段，建议立即执行"


def update_provider_pricing(provider: str, data: Dict) -> bool:
    """更新指定供应商的定价（管理接口调用）"""
    pricing = get_pricing()
    if "providers" not in pricing:
        pricing["providers"] = {}
    pricing["providers"][provider] = data
    pricing["updated_at"] = datetime.now(CST).isoformat()
    return _save_pricing_file(pricing)


def get_all_pricing_summary() -> List[Dict]:
    """获取所有供应商定价摘要（用于面板展示）"""
    data = get_pricing()
    summary = []
    for key, prov in data.get("providers", {}).items():
        summary.append({
            "id": key,
            "name": prov.get("name", key),
            "has_peak_valley": prov.get("has_peak_valley", False),
            "peak_hours": prov.get("peak_hours", []),
            "peak_multiplier": prov.get("peak_multiplier", 1.0),
            "model_count": len(prov.get("models", {})),
            "currency": prov.get("currency", "CNY"),
        })
    return summary


# 初始化：确保定价文件存在
def ensure_pricing_file():
    """确保定价文件存在，不存在则创建默认值"""
    if not os.path.exists(PRICING_FILE):
        logger.info("📝 初始化定价数据文件...")
        _save_pricing_file(_get_default_pricing())
        logger.info("✅ 定价数据文件已创建")
