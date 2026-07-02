"""
AI Cost Optimizer - Savings Calculator
计算用户通过缓存优化节省的费用，用于面板展示
"""
import logging
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta

from config import get_config
from db.database import get_db

logger = logging.getLogger(__name__)

# 各厂商标准输入价格（元/百万 tokens）
UPSTREAM_PRICES = {
    "deepseek-chat": {"input": 2.0, "cache_hit": 0.2, "output": 4.0},
    "deepseek-reasoner": {"input": 4.0, "cache_hit": 0.4, "output": 16.0},
    "gpt-4o": {"input": 17.5, "cache_hit": 8.75, "output": 70.0},
    "gpt-4o-mini": {"input": 1.05, "cache_hit": 0.525, "output": 4.2},
    "claude-sonnet-4-20250514": {"input": 21.0, "cache_hit": 2.1, "output": 105.0},
    "claude-3-5-sonnet-20241022": {"input": 21.0, "cache_hit": 2.1, "output": 105.0},
    "qwen-turbo": {"input": 2.0, "cache_hit": 0.4, "output": 6.0},
    "qwen-plus": {"input": 4.0, "cache_hit": 0.8, "output": 12.0},
}

DEFAULT_PRICES = {"input": 10.0, "cache_hit": 1.0, "output": 30.0}


def get_model_prices(model: str) -> Dict:
    """获取模型价格，找不到就用默认值"""
    # 模糊匹配
    for key, prices in UPSTREAM_PRICES.items():
        if key in model or model in key:
            return prices
    return DEFAULT_PRICES


def calculate_savings(
    input_tokens: int,
    output_tokens: int,
    model: str,
    cache_type: str = "none",
    upstream_cache_hit_tokens: int = 0,
    prefix_tokens_optimized: int = 0,
) -> Dict:
    """
    计算单次请求节省的费用

    Args:
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        model: 模型名称
        cache_type: 网关缓存命中类型 (none/exact/semantic)
        upstream_cache_hit_tokens: 上游缓存命中 token 数（从响应头读取）
        prefix_tokens_optimized: 前缀优化的 token 数

    Returns:
        {
            "original_cost": 如果不优化时的费用,
            "actual_cost": 实际费用,
            "total_saved": 总节省,
            "savings_breakdown": {
                "gateway_cache_saved": 网关缓存节省,
                "upstream_cache_saved": 上游缓存节省,
                "prefix_optimize_saved": 前缀优化节省,
            }
        }
    """
    prices = get_model_prices(model)

    # 原始费用（没有任何优化）
    original_cost = (
        input_tokens * prices["input"] / 1_000_000 +
        output_tokens * prices["output"] / 1_000_000
    )

    savings = {
        "gateway_cache_saved": 0.0,
        "upstream_cache_saved": 0.0,
        "prefix_optimize_saved": 0.0,
    }

    if cache_type in ("exact", "semantic"):
        # 网关缓存命中：完全免费（不调上游）
        savings["gateway_cache_saved"] = original_cost
    else:
        # 上游缓存命中：输入部分享受折扣
        if upstream_cache_hit_tokens > 0:
            cache_discount = prices["input"] - prices["cache_hit"]
            savings["upstream_cache_saved"] = (
                upstream_cache_hit_tokens * cache_discount / 1_000_000
            )

        # 前缀优化：让原本不会命中的缓存命中了
        # 这里保守估算，只算因为前缀整理而新增的缓存命中部分
        if prefix_tokens_optimized > 0 and upstream_cache_hit_tokens == 0:
            # 如果上游没有缓存命中，前缀优化可能帮它命中
            # 保守按 50% 命中率估算
            estimated_hit = int(prefix_tokens_optimized * 0.5)
            cache_discount = prices["input"] - prices["cache_hit"]
            savings["prefix_optimize_saved"] = (
                estimated_hit * cache_discount / 1_000_000
            )

    total_saved = sum(savings.values())
    actual_cost = max(0, original_cost - total_saved)

    return {
        "original_cost": round(original_cost, 6),
        "actual_cost": round(actual_cost, 6),
        "total_saved": round(total_saved, 6),
        "savings_breakdown": {k: round(v, 6) for k, v in savings.items()},
    }


def get_savings_dashboard(api_key_id: str) -> Dict:
    """
    获取用户的节省费用看板数据
    """
    try:
        db = get_db()
        now = datetime.now(timezone(timedelta(hours=8)))

        # 本月统计
        month_start = now.replace(day=1, hour=0, minute=0, second=0).isoformat()
        today_str = now.strftime("%Y-%m-%d")

        summary_30d = db.get_usage_summary(api_key_id, days=30)
        summary_today = db.get_usage_summary(api_key_id, days=1)

        # 从 usage_records 获取更细的节省数据
        conn = db._get_conn()

        # 本月缓存命中统计
        row = conn.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN cache_type != 'none' THEN 1 ELSE 0 END), 0) as gw_cache_hits,
                COALESCE(SUM(CASE WHEN cache_type = 'exact' THEN 1 ELSE 0 END), 0) as exact_hits,
                COALESCE(SUM(CASE WHEN cache_type = 'semantic' THEN 1 ELSE 0 END), 0) as semantic_hits,
                COALESCE(SUM(CAST(json_extract(savings_json, '$.upstream_cache_saved') AS REAL)), 0) as upstream_saved,
                COALESCE(SUM(CAST(json_extract(savings_json, '$.prefix_optimize_saved') AS REAL)), 0) as prefix_saved,
                COALESCE(SUM(CAST(json_extract(savings_json, '$.gateway_cache_saved') AS REAL)), 0) as gw_saved,
                COALESCE(SUM(CAST(json_extract(savings_json, '$.total_saved') AS REAL)), 0) as total_saved_money,
                COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                COALESCE(SUM(output_tokens), 0) as total_output_tokens
            FROM usage_records
            WHERE api_key_id = ? AND created_at >= ?
        """, (api_key_id, month_start)).fetchone()

        # 每日趋势（最近7天）
        daily_rows = conn.execute("""
            SELECT
                DATE(created_at) as day,
                COUNT(*) as calls,
                COALESCE(SUM(CASE WHEN cache_type != 'none' THEN 1 ELSE 0 END), 0) as cache_hits,
                COALESCE(SUM(CAST(json_extract(savings_json, '$.total_saved') AS REAL)), 0) as saved
            FROM usage_records
            WHERE api_key_id = ? AND created_at >= ?
            GROUP BY DATE(created_at)
            ORDER BY day
        """, (api_key_id, (now - timedelta(days=7)).isoformat())).fetchall()

        conn.close()

        total_calls = row["gw_cache_hits"] + (summary_30d.get("total_calls", 0) - row["gw_cache_hits"]) if row else 0
        total_calls = summary_30d.get("total_calls", 0)

        cache_hit_rate = (
            row["gw_cache_hits"] / total_calls * 100
            if total_calls > 0 else 0
        )

        return {
            "period": "本月",
            "total_calls": total_calls,
            "calls_today": summary_today.get("calls_today", 0),
            "cache_hit_rate": round(cache_hit_rate, 1),
            "gateway_cache_hits": row["gw_cache_hits"] if row else 0,
            "exact_cache_hits": row["exact_hits"] if row else 0,
            "semantic_cache_hits": row["semantic_hits"] if row else 0,
            "savings": {
                "gateway_cache": round(row["gw_saved"] if row else 0, 4),
                "upstream_cache": round(row["upstream_saved"] if row else 0, 4),
                "prefix_optimize": round(row["prefix_saved"] if row else 0, 4),
                "total": round(row["total_saved_money"] if row else 0, 4),
            },
            "tokens": {
                "input_total": row["total_input_tokens"] if row else 0,
                "output_total": row["total_output_tokens"] if row else 0,
            },
            "daily_trend": [
                {
                    "day": r["day"],
                    "calls": r["calls"],
                    "cache_hits": r["cache_hits"],
                    "saved": round(r["saved"], 4),
                }
                for r in daily_rows
            ],
        }
    except Exception as e:
        logger.error(f"get_savings_dashboard error: {e}")
        return {
            "total_calls": 0,
            "calls_today": 0,
            "cache_hit_rate": 0,
            "savings": {"gateway_cache": 0, "upstream_cache": 0, "prefix_optimize": 0, "total": 0},
            "daily_trend": [],
        }
