"""
AI Cost Optimizer - Peak/Valley Scheduler
峰谷调度：判断当前是否高峰，计算低峰时间，决定任务是否延迟
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

from config import get_config, DeepSeekPricing
from models import TaskPriority

logger = logging.getLogger(__name__)
CST = timezone(timedelta(hours=8))


def is_peak_time(now: Optional[datetime] = None) -> bool:
    """判断当前是否为 DeepSeek 高峰时段（北京时间）"""
    if now is None:
        now = datetime.now(CST)
    hour = now.hour
    pricing = DeepSeekPricing()
    for start, end in pricing.peak_hours:
        if start <= hour < end:
            return True
    return False


def get_next_offpeak(from_time: Optional[datetime] = None) -> datetime:
    """计算下一个低峰时段开始时间"""
    if from_time is None:
        from_time = datetime.now(CST)

    pricing = DeepSeekPricing()
    hour = from_time.hour
    peaks = sorted(pricing.peak_hours)

    for start, end in peaks:
        if hour < start:
            # 在高峰之前 → 现在就是低峰
            return from_time
        elif start <= hour < end:
            # 在高峰期内 → 等到高峰结束
            return from_time.replace(hour=end, minute=0, second=0, microsecond=0)

    # 最后一个高峰之后 → 已经是低峰
    return from_time


def should_delay(priority: TaskPriority, now: Optional[datetime] = None) -> Tuple[bool, Optional[datetime]]:
    """
    判断任务是否应该延迟到低峰执行

    Returns:
        (should_delay, scheduled_time)
        - should_delay: 是否应延迟
        - scheduled_time: 计划执行时间（如果不延迟则为 None）
    """
    current_peak = is_peak_time(now)

    if not current_peak:
        # 当前是低峰，不需要延迟
        return False, None

    if priority == TaskPriority.IMMEDIATE:
        # 紧急任务，不延迟，高峰也执行
        return False, None
    elif priority == TaskPriority.HIGH:
        # 高优先级，等到当前高峰结束
        offpeak = get_next_offpeak(now)
        wait_minutes = (offpeak - (now or datetime.now(CST))).total_seconds() / 60
        if wait_minutes <= 120:  # 最多等2小时
            return True, offpeak
        return False, None
    elif priority == TaskPriority.NORMAL:
        # 普通优先级，等到下一个低峰
        offpeak = get_next_offpeak(now)
        return True, offpeak
    elif priority == TaskPriority.LOW:
        # 低优先级，找最便宜的时间段（最长的低峰窗口）
        offpeak = _find_cheapest_window(now)
        return True, offpeak

    return False, None


def _find_cheapest_window(from_time: Optional[datetime] = None) -> datetime:
    """找到最便宜的低峰窗口（简化实现：返回下一个低峰开始）"""
    return get_next_offpeak(from_time)


def get_price_multiplier(now: Optional[datetime] = None) -> float:
    """获取当前价格倍率（高峰=2.0，低峰=1.0）"""
    if is_peak_time(now):
        return 2.0
    return 1.0


def get_scheduling_info(now: Optional[datetime] = None) -> dict:
    """获取当前调度信息（用于 API 返回）"""
    now = now or datetime.now(CST)
    peak = is_peak_time(now)
    next_offpeak = get_next_offpeak(now)

    return {
        "current_time": now.isoformat(),
        "is_peak": peak,
        "price_multiplier": 2.0 if peak else 1.0,
        "next_offpeak": next_offpeak.isoformat() if peak else None,
        "peak_hours": [(s, e) for s, e in DeepSeekPricing().peak_hours],
        "recommendation": "当前为低峰期，建议立即执行" if not peak else "当前为高峰期，非紧急任务建议延迟执行"
    }
