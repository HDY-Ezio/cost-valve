"""
AI Cost Optimizer - Data Models (Pydantic)
"""
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import uuid

CST = timezone(timedelta(hours=8))


# ============================================================
# Enums
# ============================================================

class TaskPriority(str, Enum):
    IMMEDIATE = "immediate"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class CacheType(str, Enum):
    NONE = "none"
    EXACT = "exact"
    SEMANTIC = "semantic"


# ============================================================
# OpenAI Compatible Request/Response Models
# ============================================================

class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """OpenAI 兼容的 Chat Completion 请求"""
    model: str = ""
    messages: List[ChatMessage]
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stream: bool = False
    # 扩展字段（非标准，代理层使用）
    priority: TaskPriority = TaskPriority.IMMEDIATE
    enable_cache: bool = True
    enable_semantic_cache: bool = True
    enable_prompt_optimize: bool = True
    # 可选 metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = None


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    """OpenAI 兼容的 Chat Completion 响应"""
    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: List[Choice] = Field(default_factory=list)
    usage: UsageInfo = Field(default_factory=UsageInfo)


class DeltaMessage(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: DeltaMessage
    finish_reason: Optional[str] = None


class ChatCompletionStreamChunk(BaseModel):
    """SSE 流式响应的单个 chunk"""
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: List[StreamChoice] = Field(default_factory=list)


# ============================================================
# Proxy Internal Models
# ============================================================

class ProxyResult(BaseModel):
    """代理内部处理结果"""
    request_id: str = ""
    success: bool = False
    provider: str = ""
    model: str = ""
    # 成本信息
    original_cost: float = 0.0
    actual_cost: float = 0.0
    saved_cost: float = 0.0
    # 缓存
    cache_hit: CacheType = CacheType.NONE
    # 调度
    was_delayed: bool = False
    scheduled_at: str = ""
    # Prompt 瘦身
    tokens_saved: int = 0
    # 错误
    error: str = ""


class UsageSummary(BaseModel):
    """用量统计摘要"""
    api_key_id: str = ""
    period: str = ""
    total_calls: int = 0
    cache_hits: int = 0
    exact_cache_hits: int = 0
    semantic_cache_hits: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    total_saved: float = 0.0
    proxy_fee: float = 0.0
    calls_today: int = 0


class BudgetStatus(BaseModel):
    """预算状态"""
    api_key_id: str = ""
    monthly_budget: float = 0.0
    spent_this_month: float = 0.0
    remaining: float = 0.0
    percent_used: float = 0.0
    status: str = "normal"  # normal / warning / degraded / exceeded
    calls_remaining: int = 0


# ============================================================
# Helper
# ============================================================

def generate_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:16]}"


def now_iso() -> str:
    return datetime.now(CST).isoformat()
