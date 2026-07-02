"""
AI Cost Optimizer - Pricing Engine
峰谷定价 + 成本计算
"""
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional
from config import DeepSeekPricing, get_config

# 北京时间
CST = timezone(timedelta(hours=8))


def is_peak_time(now: Optional[datetime] = None) -> bool:
    """判断当前是否为高峰时段（北京时间）"""
    if now is None:
        now = datetime.now(CST)
    hour = now.hour
    pricing = DeepSeekPricing()
    for start, end in pricing.peak_hours:
        if start <= hour < end:
            return True
    return False


def get_next_offpeak_time(from_time: Optional[datetime] = None) -> datetime:
    """计算下一个低峰时段的开始时间"""
    if from_time is None:
        from_time = datetime.now(CST)

    pricing = DeepSeekPricing()
    hour = from_time.hour

    # 按高峰时段排序
    peaks = sorted(pricing.peak_hours)

    for start, end in peaks:
        if hour < start:
            # 当前在第一个高峰之前，还没进入高峰
            return from_time  # 现在就是低峰
        elif start <= hour < end:
            # 当前在高峰期内，等到这个高峰结束
            return from_time.replace(hour=end, minute=0, second=0, microsecond=0)

    # 当前在最后一个高峰之后，已经是低峰
    return from_time


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_hit_tokens: int = 0,
    is_peak: bool = False,
    provider: str = "deepseek",
) -> Tuple[float, float]:
    """
    计算 API 调用成本

    返回: (原始成本, 实际成本) 单位：元
    """
    pricing = DeepSeekPricing()

    if is_peak:
        input_price = pricing.input_peak / 1_000_000      # 元/token
        output_price = pricing.output_peak / 1_000_000
        cache_price = pricing.cache_hit_peak / 1_000_000
    else:
        input_price = pricing.input_normal / 1_000_000
        output_price = pricing.output_normal / 1_000_000
        cache_price = pricing.cache_hit_normal / 1_000_000

    # 原始成本（假设全部走非缓存 + 高峰）
    original_input_price = pricing.input_peak / 1_000_000
    original_output_price = pricing.output_peak / 1_000_000
    original_cost = (input_tokens * original_input_price +
                     output_tokens * original_output_price)

    # 实际成本
    non_cache_input = input_tokens - cache_hit_tokens
    actual_cost = (cache_hit_tokens * cache_price +
                   non_cache_input * input_price +
                   output_tokens * output_price)

    return round(original_cost, 6), round(actual_cost, 6)


def calculate_savings(
    input_tokens: int,
    output_tokens: int,
    original_cache_rate: float,
    optimized_cache_rate: float,
    was_peak: bool,
    moved_to_offpeak: bool,
) -> dict:
    """
    计算优化后的节省金额

    Args:
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        original_cache_rate: 原始缓存命中率
        optimized_cache_rate: 优化后缓存命中率
        was_peak: 原来是否在高峰期执行
        moved_to_offpeak: 是否移到了低峰期

    Returns:
        节省详情
    """
    pricing = DeepSeekPricing()

    # 原始成本
    if was_peak:
        orig_input_price = pricing.input_peak / 1_000_000
        orig_output_price = pricing.output_peak / 1_000_000
        orig_cache_price = pricing.cache_hit_peak / 1_000_000
    else:
        orig_input_price = pricing.input_normal / 1_000_000
        orig_output_price = pricing.output_normal / 1_000_000
        orig_cache_price = pricing.cache_hit_normal / 1_000_000

    orig_cache_tokens = int(input_tokens * original_cache_rate)
    orig_non_cache = input_tokens - orig_cache_tokens
    original_cost = (orig_cache_tokens * orig_cache_price +
                     orig_non_cache * orig_input_price +
                     output_tokens * orig_output_price)

    # 优化后成本
    if moved_to_offpeak:
        opt_input_price = pricing.input_normal / 1_000_000
        opt_output_price = pricing.output_normal / 1_000_000
        opt_cache_price = pricing.cache_hit_normal / 1_000_000
    else:
        opt_input_price = orig_input_price
        opt_output_price = orig_output_price
        opt_cache_price = orig_cache_price

    opt_cache_tokens = int(input_tokens * optimized_cache_rate)
    opt_non_cache = input_tokens - opt_cache_tokens
    optimized_cost = (opt_cache_tokens * opt_cache_price +
                      opt_non_cache * opt_input_price +
                      output_tokens * opt_output_price)

    saved = original_cost - optimized_cost
    saved_pct = (saved / original_cost * 100) if original_cost > 0 else 0

    return {
        "original_cost": round(original_cost, 6),
        "optimized_cost": round(optimized_cost, 6),
        "saved_cost": round(saved, 6),
        "saved_percent": round(saved_pct, 1),
        "cache_improvement": f"{original_cache_rate*100:.0f}% → {optimized_cache_rate*100:.0f}%",
        "time_optimization": "peak→offpeak" if moved_to_offpeak else "unchanged",
    }


def estimate_proxy_fee(call_count: int, monthly_quota: int = 1000) -> float:
    """计算代理服务费"""
    config = get_config()
    if call_count <= monthly_quota:
        return 0.0
    paid_calls = call_count - monthly_quota
    return round(paid_calls * config.price_per_call, 2)
