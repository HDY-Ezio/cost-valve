"""
AI Cost Optimizer - Budget Control
预算控制 + 告警 + 自动降级
"""
import logging
import uuid
from typing import Dict, Optional, Tuple

from config import get_config
from db.database import get_db

logger = logging.getLogger(__name__)


class BudgetAction:
    ALLOW = "allow"           # 允许执行
    DEGRADE = "degrade"       # 降级（切小模型）
    WARN = "warn"             # 告警但允许
    BLOCK = "block"           # 阻止执行


def check_budget(api_key_id: str) -> Tuple[str, Dict]:
    """
    检查预算状态

    Returns:
        (action, status_info)
        action: allow / degrade / warn / block
    """
    try:
        db = get_db()
        cfg = get_config()

        # 获取 key 信息
        # 需要从 usage 记录中汇总当月花费
        summary = db.get_usage_summary(api_key_id, days=30)
        spent = summary.get("total_cost", 0.0) + summary.get("total_proxy_fee", 0.0)
        calls = summary.get("total_calls", 0)

        # 获取 key 的预算设置
        # 简化：从 api_keys 表查
        key_info = _get_key_info(api_key_id)
        monthly_budget = key_info.get("monthly_budget", cfg.default_monthly_budget)
        monthly_quota = key_info.get("monthly_quota", cfg.free_quota_monthly)
        used = key_info.get("used_this_month", calls)

        percent = spent / monthly_budget if monthly_budget > 0 else 0
        calls_percent = used / monthly_quota if monthly_quota > 0 else 0

        status = {
            "api_key_id": api_key_id,
            "monthly_budget": monthly_budget,
            "spent_this_month": round(spent, 4),
            "remaining": round(max(0, monthly_budget - spent), 4),
            "percent_used": round(percent * 100, 1),
            "calls_used": used,
            "calls_remaining": max(0, monthly_quota - used),
        }

        # 判断动作
        if percent >= 1.0:
            # 超出预算 → 阻止
            status["status"] = "exceeded"
            _record_alert(api_key_id, "budget_exceeded",
                          f"Budget exceeded: {spent:.2f}/{monthly_budget:.2f}元")
            return BudgetAction.BLOCK, status

        if percent >= cfg.budget_degrade_threshold:
            # 接近预算 → 降级
            status["status"] = "degraded"
            _record_alert(api_key_id, "budget_degraded",
                          f"Budget {percent*100:.0f}% used, degrading to cheaper models")
            return BudgetAction.DEGRADE, status

        if percent >= cfg.budget_warn_threshold:
            # 到达警告线
            status["status"] = "warning"
            _record_alert(api_key_id, "budget_warning",
                          f"Budget {percent*100:.0f}% used")
            return BudgetAction.WARN, status

        status["status"] = "normal"
        return BudgetAction.ALLOW, status

    except Exception as e:
        logger.error(f"check_budget error: {e}")
        # 出错时默认允许（不阻断用户）
        return BudgetAction.ALLOW, {"status": "normal", "error": str(e)}


def check_quota(api_key_id: str) -> Tuple[bool, Dict]:
    """
    检查月度配额

    Returns:
        (allowed, info)
    """
    try:
        db = get_db()
        cfg = get_config()
        key_info = _get_key_info(api_key_id)

        monthly_quota = key_info.get("monthly_quota", cfg.free_quota_monthly)
        used = key_info.get("used_this_month", 0)

        if used >= monthly_quota:
            # 超出免费配额 → 检查余额
            balance = key_info.get("balance", 0.0)
            if balance >= cfg.price_per_call:
                return True, {
                    "allowed": True,
                    "reason": "paid",
                    "proxy_fee": cfg.price_per_call,
                    "remaining_quota": 0,
                    "balance": balance,
                }
            else:
                return False, {
                    "allowed": False,
                    "reason": "quota_exceeded_no_balance",
                    "message": f"月度配额已用完({used}/{monthly_quota})且余额不足",
                    "remaining_quota": 0,
                }

        return True, {
            "allowed": True,
            "reason": "free_quota",
            "proxy_fee": 0.0,
            "remaining_quota": monthly_quota - used,
        }
    except Exception as e:
        logger.error(f"check_quota error: {e}")
        return True, {"allowed": True, "reason": "error_fallback", "error": str(e)}


def calculate_proxy_fee(api_key_id: str) -> float:
    """计算本次调用的代理服务费"""
    try:
        cfg = get_config()
        key_info = _get_key_info(api_key_id)
        monthly_quota = key_info.get("monthly_quota", cfg.free_quota_monthly)
        used = key_info.get("used_this_month", 0)

        if used < monthly_quota:
            return 0.0  # 免费额度内
        return cfg.price_per_call
    except Exception:
        return 0.0


def _get_key_info(api_key_id: str) -> Dict:
    """获取 key 信息（简化版，从数据库查）"""
    try:
        db = get_db()
        conn = db._get_conn()
        row = conn.execute("SELECT * FROM api_keys WHERE key_id = ?", (api_key_id,)).fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def _record_alert(api_key_id: str, alert_type: str, message: str):
    """记录预算告警"""
    try:
        db = get_db()
        db.record_budget_alert(api_key_id, alert_type, message)
    except Exception as e:
        logger.error(f"_record_alert error: {e}")
