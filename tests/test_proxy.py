"""
AI Cost Optimizer - 基础测试
"""
import sys
import os
import json
import time

# 确保路径正确
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

# 设置 mock 模式
os.environ["MOCK_MODE"] = "true"
os.environ["APP_DEBUG"] = "false"

from main import app
from config import get_config, reset_config
from db.database import init_db
from core.cache import make_cache_key, cosine_similarity, _mock_embedding
from core.scheduler import is_peak_time, get_next_offpeak, should_delay
from core.router import estimate_complexity, select_model
from core.prompt_optimizer import optimize_messages
from core.auth import hash_api_key, authenticate

# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def client():
    """测试客户端"""
    reset_config()
    init_db("./data/test_ai_cost_optimizer.db")
    with TestClient(app) as c:
        yield c
    # 清理
    try:
        os.remove("./data/test_ai_cost_optimizer.db")
    except Exception:
        pass


@pytest.fixture
def auth_header():
    """默认认证头"""
    return {"Authorization": "Bearer aco-default-dev-key-2026"}


# ============================================================
# 基础健康检查
# ============================================================

class TestHealthCheck:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "AI Cost Optimizer"
        assert data["status"] == "running"

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ============================================================
# API Key 认证
# ============================================================

class TestAuth:
    def test_no_auth(self, client):
        resp = client.post("/v1/chat/completions",
                           json={"messages": [{"role": "user", "content": "hi"}]})
        assert resp.status_code == 401

    def test_invalid_key(self, client):
        resp = client.post("/v1/chat/completions",
                           json={"messages": [{"role": "user", "content": "hi"}]},
                           headers={"Authorization": "Bearer invalid-key"})
        assert resp.status_code == 401

    def test_valid_key(self, client, auth_header):
        resp = client.post("/v1/chat/completions",
                           json={"messages": [{"role": "user", "content": "hello"}]},
                           headers=auth_header)
        assert resp.status_code == 200


# ============================================================
# Chat Completion (非流式)
# ============================================================

class TestChatCompletion:
    def test_basic_completion(self, client, auth_header):
        resp = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "Hello, how are you?"}],
            "stream": False,
        }, headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["message"]["content"] is not None

    def test_with_system_message(self, client, auth_header):
        resp = client.post("/v1/chat/completions", json={
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is 2+2?"}
            ],
        }, headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "choices" in data

    def test_with_model(self, client, auth_header):
        resp = client.post("/v1/chat/completions", json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "Test with model"}],
        }, headers=auth_header)
        assert resp.status_code == 200

    def test_with_temperature(self, client, auth_header):
        resp = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "Test temp"}],
            "temperature": 0.7,
            "max_tokens": 100,
        }, headers=auth_header)
        assert resp.status_code == 200

    def test_cache_hit(self, client, auth_header):
        """相同请求第二次应命中精确缓存"""
        payload = {
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "stream": False,
        }
        # 第一次请求
        resp1 = client.post("/v1/chat/completions", json=payload, headers=auth_header)
        assert resp1.status_code == 200

        # 第二次请求（应命中缓存）
        resp2 = client.post("/v1/chat/completions", json=payload, headers=auth_header)
        assert resp2.status_code == 200
        data2 = resp2.json()
        # 缓存命中时返回的内容应与第一次相同
        assert data2["choices"][0]["message"]["content"] == resp1.json()["choices"][0]["message"]["content"]


# ============================================================
# 流式 Chat Completion
# ============================================================

class TestStreamCompletion:
    def test_basic_stream(self, client, auth_header):
        resp = client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "Hello streaming"}],
            "stream": True,
        }, headers=auth_header)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")

        # 检查 SSE 数据
        content = resp.text
        assert "data:" in content
        assert "[DONE]" in content


# ============================================================
# 管理 API
# ============================================================

class TestManagementAPI:
    def test_providers(self, client, auth_header):
        resp = client.get("/v1/providers", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data

    def test_models(self, client, auth_header):
        resp = client.get("/v1/models", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data

    def test_schedule_info(self, client):
        resp = client.get("/v1/schedule/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_peak" in data
        assert "peak_hours" in data

    def test_usage(self, client, auth_header):
        resp = client.get("/v1/usage", headers=auth_header)
        assert resp.status_code == 200

    def test_budget(self, client, auth_header):
        resp = client.get("/v1/budget", headers=auth_header)
        assert resp.status_code == 200


# ============================================================
# 单元测试
# ============================================================

class TestCacheKey:
    def test_same_messages_same_key(self):
        messages = [{"role": "user", "content": "hello"}]
        key1 = make_cache_key("model-a", messages)
        key2 = make_cache_key("model-a", messages)
        assert key1 == key2

    def test_different_messages_different_key(self):
        msg1 = [{"role": "user", "content": "hello"}]
        msg2 = [{"role": "user", "content": "world"}]
        key1 = make_cache_key("model-a", msg1)
        key2 = make_cache_key("model-a", msg2)
        assert key1 != key2

    def test_different_model_different_key(self):
        messages = [{"role": "user", "content": "hello"}]
        key1 = make_cache_key("model-a", messages)
        key2 = make_cache_key("model-b", messages)
        assert key1 != key2


class TestCosineSimilarity:
    def test_identical_vectors(self):
        vec = [1.0, 0.0, 0.0]
        assert abs(cosine_similarity(vec, vec) - 1.0) < 0.001

    def test_orthogonal_vectors(self):
        assert abs(cosine_similarity([1, 0], [0, 1])) < 0.001

    def test_opposite_vectors(self):
        assert abs(cosine_similarity([1, 0], [-1, 0]) + 1.0) < 0.001


class TestScheduler:
    def test_peak_time_detection(self):
        # 测试不同时间段的检测
        from datetime import datetime, timezone, timedelta
        CST = timezone(timedelta(hours=8))

        # 10:00 是高峰
        peak_time = datetime(2026, 7, 2, 10, 0, 0, tzinfo=CST)
        assert is_peak_time(peak_time) is True

        # 13:00 不是高峰
        offpeak_time = datetime(2026, 7, 2, 13, 0, 0, tzinfo=CST)
        assert is_peak_time(offpeak_time) is False

        # 22:00 不是高峰
        night_time = datetime(2026, 7, 2, 22, 0, 0, tzinfo=CST)
        assert is_peak_time(night_time) is False


class TestRouter:
    def test_simple_message(self):
        messages = [{"role": "user", "content": "Hi"}]
        assert estimate_complexity(messages) == "simple"

    def test_complex_message(self):
        messages = [
            {"role": "system", "content": "You are an expert coder. " * 50},
            {"role": "user", "content": "```python\ndef complex_function():\n    pass\n``` Explain this"},
        ]
        assert estimate_complexity(messages) in ("medium", "complex")


class TestPromptOptimizer:
    def test_strip_whitespace(self):
        messages = [{"role": "user", "content": "hello\n\n\n\n\nworld"}]
        optimized, saved = optimize_messages(messages)
        assert "\n\n\n\n" not in optimized[0]["content"]

    def test_disabled(self):
        messages = [{"role": "user", "content": "test"}]
        optimized, saved = optimize_messages(messages, enabled=False)
        assert optimized == messages
        assert saved == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
