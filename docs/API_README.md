# AI Cost Optimizer - API 使用文档

## 快速开始

### 一句话说明
把 `base_url` 从 `https://api.deepseek.com` 改成我们的代理地址，其他代码都不用改，自动帮你省 50-90% API 费用。

### 安装 & 启动

```bash
# 安装依赖
pip install -r requirements.txt

# 启动（mock 模式，不需要 API key）
MOCK_MODE=true python main.py

# 启动（生产模式，配置真实 API key）
MOCK_MODE=false DEEPSEEK_API_KEY=sk-xxx python main.py
```

服务默认运行在 `http://localhost:8000`

---

## API 接口

### 基础信息

| 项目 | 值 |
|------|-----|
| Base URL | `http://localhost:8000/v1` |
| 认证方式 | Bearer Token (API Key) |
| 格式 | OpenAI 兼容 |
| 默认测试 Key | `aco-default-dev-key-2026` |

### 1. Chat Completions (核心接口)

**POST** `/v1/chat/completions`

完全兼容 OpenAI Chat Completion API 格式。

#### 非流式请求

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer aco-default-dev-key-2026" \
  -d '{
    "model": "deepseek-chat",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Hello!"}
    ],
    "temperature": 0.7,
    "stream": false
  }'
```

#### 流式请求 (SSE)

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer aco-default-dev-key-2026" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

#### Python SDK 使用

```python
from openai import OpenAI

# 只需要改 base_url！
client = OpenAI(
    api_key="aco-default-dev-key-2026",
    base_url="http://localhost:8000/v1"
)

# 非流式
response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)

# 流式
stream = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,
)
for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

#### 响应格式

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1720000000,
  "model": "deepseek-chat",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
  "_optimization": {
    "request_id": "req-xxx",
    "provider": "deepseek",
    "model": "deepseek-chat",
    "cache_hit": "none",
    "tokens_saved": 5
  }
}
```

#### 扩展参数（可选）

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `priority` | string | `"immediate"` | 任务优先级: `immediate`/`high`/`normal`/`low` |
| `enable_cache` | bool | `true` | 是否启用精确缓存 |
| `enable_semantic_cache` | bool | `true` | 是否启用语义缓存 |
| `enable_prompt_optimize` | bool | `true` | 是否启用 Prompt 瘦身 |

```json
{
  "model": "deepseek-chat",
  "messages": [{"role": "user", "content": "Hello!"}],
  "priority": "normal",
  "enable_cache": true,
  "enable_semantic_cache": true,
  "enable_prompt_optimize": true
}
```

---

### 2. 创建 API Key

**POST** `/v1/api-keys`

```bash
curl -X POST http://localhost:8000/v1/api-keys \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Project",
    "monthly_quota": 1000,
    "monthly_budget": 100.0
  }'
```

响应：
```json
{
  "message": "API key created successfully",
  "data": {
    "key_id": "abc123",
    "api_key": "aco-xxx",
    "name": "My Project",
    "monthly_quota": 1000,
    "monthly_budget": 100.0
  }
}
```

---

### 3. 用量统计 (Dashboard)

**GET** `/v1/usage`

```bash
curl http://localhost:8000/v1/usage \
  -H "Authorization: Bearer aco-default-dev-key-2026"
```

响应：
```json
{
  "overview": {
    "total_calls_30d": 150,
    "calls_today": 23,
    "total_tokens_30d": 45000,
    "total_cost_30d": 0.85,
    "total_saved_30d": 0.42,
    "total_proxy_fee_30d": 0.0,
    "cache_hit_rate": 35.2,
    "tokens_saved_by_optimization": 1200
  },
  "cache": {
    "total_cache_hits": 52,
    "exact_cache_hits": 30,
    "semantic_cache_hits": 22,
    "cache_hit_rate": 35.2
  },
  "budget": {
    "api_key_id": "xxx",
    "monthly_budget": 100.0,
    "spent_this_month": 0.85,
    "remaining": 99.15,
    "percent_used": 0.9,
    "status": "normal"
  },
  "daily_trend": [
    {"day": "2026-07-01", "calls": 20, "tokens": 6000, "cost": 0.12, "saved": 0.06},
    {"day": "2026-07-02", "calls": 23, "tokens": 7200, "cost": 0.15, "saved": 0.08}
  ]
}
```

---

### 4. 预算状态

**GET** `/v1/budget`

```bash
curl http://localhost:8000/v1/budget \
  -H "Authorization: Bearer aco-default-dev-key-2026"
```

---

### 5. 调度信息

**GET** `/v1/schedule/info`

查看当前峰谷状态和调度建议。

```bash
curl http://localhost:8000/v1/schedule/info
```

响应：
```json
{
  "current_time": "2026-07-02T10:30:00+08:00",
  "is_peak": true,
  "price_multiplier": 2.0,
  "next_offpeak": "2026-07-02T12:00:00+08:00",
  "peak_hours": [[9, 12], [14, 18]],
  "recommendation": "当前为高峰期，非紧急任务建议延迟执行"
}
```

---

### 6. 提供商列表

**GET** `/v1/providers`

### 7. 模型列表

**GET** `/v1/models` (需要认证)

---

## 省钱逻辑说明

### 自动优化流程

```
用户请求 → 认证 → 预算检查 → 配额检查
    ↓
  检查精确缓存 → 命中? → 直接返回 (不计次)
    ↓ 未命中
  检查语义缓存 → 命中? → 直接返回 (不计次)
    ↓ 未命中
  峰谷调度判断 → 非紧急+高峰? → 建议延迟
    ↓
  Prompt 瘦身 → 减少 token
    ↓
  智能模型路由 → 简单任务用小模型
    ↓
  选厂商 → 转发请求
    ↓ 失败?
  自动 Fallback 到备用厂商
    ↓
  写入缓存 → 记录用量 → 返回结果
```

### 计费规则

| 场景 | 是否计费 | 说明 |
|------|---------|------|
| 普通调用 | ¥0.01/次 | 超出免费额度后 |
| 免费额度 | ¥0 | 每月1000次 |
| 精确缓存命中 | ¥0 | 不计次 |
| 语义缓存命中 | ¥0 | 不计次 |

### 峰谷时段 (DeepSeek)

| 时段 | 价格倍率 | 说明 |
|------|---------|------|
| 9:00-12:00 | 2x | 高峰 |
| 14:00-18:00 | 2x | 高峰 |
| 其他时间 | 1x | 低峰 |

---

## 环境变量配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `APP_HOST` | 服务地址 | `0.0.0.0` |
| `APP_PORT` | 服务端口 | `8000` |
| `APP_DEBUG` | 调试模式 | `false` |
| `MOCK_MODE` | Mock模式(无需API Key) | `true` |
| `DB_PATH` | 数据库路径 | `./data/ai_cost_optimizer.db` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `DEEPSEEK_BASE_URL` | DeepSeek API地址 | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | DeepSeek默认模型 | `deepseek-chat` |
| `ALIYUN_API_KEY` | 阿里云百炼 API Key | - |
| `ALIYUN_BASE_URL` | 阿里云API地址 | `https://dashscope.aliyuncs.com/compatible-mode` |
| `GENERIC_API_KEY` | 通用提供商 API Key | - |
| `GENERIC_BASE_URL` | 通用提供商地址 | - |

---

## 测试

```bash
# 运行测试
cd ai-cost-optimizer
pip install pytest httpx
python -m pytest tests/ -v

# 手动测试
curl http://localhost:8000/
curl http://localhost:8000/health
curl http://localhost:8000/v1/schedule/info
```

---

## 项目结构

```
ai-cost-optimizer/
├── main.py              # FastAPI 入口
├── config.py            # 配置管理
├── models.py            # 数据模型
├── requirements.txt     # 依赖
├── core/
│   ├── proxy.py         # API代理核心（流式+非流式）
│   ├── providers.py     # 厂商适配器
│   ├── scheduler.py     # 峰谷调度
│   ├── cache.py         # 精确+语义缓存
│   ├── router.py        # 智能模型路由
│   ├── prompt_optimizer.py  # Prompt瘦身
│   ├── fallback.py      # 多厂商Fallback
│   ├── budget.py        # 预算控制
│   ├── usage.py         # 用量统计
│   └── auth.py          # API Key认证
├── db/
│   └── database.py      # SQLite数据库
├── docs/
│   └── API_README.md    # 本文档
└── tests/
    └── test_proxy.py    # 测试
```

---

**创建时间:** 2026-07-02  
**版本:** 1.0.0-mvp
