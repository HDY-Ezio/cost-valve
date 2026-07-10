"""
节能阀 Cost Valve - 数据模型 (Pydantic)
AI API 成本优化中间件 - 开源版
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

class CacheType(str, Enum):
    NONE = "none"
    EXACT = "exact"


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
    enable_cache: bool = True
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


# ============================================================
# Helper
# ============================================================

def generate_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:16]}"


def now_iso() -> str:
    return datetime.now(CST).isoformat()
