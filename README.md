<div align="center">

# 💸 Cost Valve — AI API Cost Optimization Gateway

**Slash your LLM API costs by 30%-70% with zero code changes**

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Stars](https://img.shields.io/github/stars/HDY-Ezio/cost-valve?style=social)](https://github.com/HDY-Ezio/cost-valve/stargazers)

**[English](README.md) | [中文](README.zh-CN.md)**

---

</div>

---

## ⚡ Try in 30 Seconds (Zero Setup)

No installation needed. Copy this curl command, replace with your API key, and see it work:

```bash
curl -X POST https://api.costvalve.cloud/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-YOUR_DEEPSEEK_KEY" \
  -H "X-Upstream-URL: https://api.deepseek.com" \
  -d '{
    "model": "deepseek-chat",
    "messages": [{"role": "user", "content": "What is cost valve?"}]
  }'
```

> 🎯 **1st call**: Normal forwarding, ~1-2 seconds
>
> ⚡ **2nd call (same question)**: Cache hit — instant response, **100% token savings**

**Works with your existing API key — no registration, no sign-up.**

### One-Click Python Demo

```bash
curl -O https://raw.githubusercontent.com/HDY-Ezio/cost-valve/main/examples/quick_demo.py
# Edit the file, set your API key
python quick_demo.py
```

See [`examples/quick_demo.py`](examples/quick_demo.py) for a complete demo that shows cache savings in action.

---

## 🎯 Why Cost Valve?

Every AI team is bleeding money on API calls. The same questions get asked hundreds of times, and you pay for every token — every single time.

**Cost Valve sits between your app and LLM APIs, automatically catching redundant requests before they burn through your budget.**

```
Before: App → LLM API (pay for every call)
After:  App → Cost Valve → LLM API (cache hits = free)
```

### ✨ Key Results

- **30-70% cost reduction** in real-world scenarios
- **One-line integration** — just change your base_url
- **Zero learning curve** — fully OpenAI-compatible API
- **Real-time dashboard** — see exactly how much you're saving

---

## ⚡ Core Features

| Feature | Description | Cost Savings |
|---------|-------------|-------------|
| 🎯 **Exact Cache** | Identical prompts return cached results instantly | 20-40% |
| 🧠 **Prefix Optimization** | Automatically restructures prompts to maximize upstream provider cache hits | 10-30% |
| ✂️ **Prompt Slimming** | Removes redundant whitespace, duplicates, and boilerplate | 5-15% |
| 📊 **Usage Dashboard** | Real-time stats: calls, cache hit rate, tokens saved | — |
| 🔌 **Multi-Provider** | DeepSeek, OpenAI, Qwen, GLM, Claude, Gemini, and any OpenAI-compatible API | — |
| 🐳 **Docker Ready** | One command deployment with docker-compose | — |

---

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
git clone https://github.com/HDY-Ezio/cost-valve.git
cd cost-valve
cp .env.example .env
# Edit .env and add your API keys
docker-compose up -d
```

### Option 2: Python Directly

```bash
git clone https://github.com/HDY-Ezio/cost-valve.git
cd cost-valve
pip install -r requirements.txt
cp .env.example .env
python main.py
```

### Option 3: Zero Setup (Pass-through Mode)

No env vars needed — pass upstream keys via headers on each request:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="anything",
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Hello!"}],
    extra_headers={
        "X-Upstream-Key": "sk-your-upstream-key",
        "X-Upstream-URL": "https://api.deepseek.com",
    }
)
```

---

## 🔧 How It Works

```
Client Request
    ↓
┌─────────────────────────────────┐
│    Cost Valve Gateway            │
│  ┌───────────────────────────┐  │
│  │ 1. Exact Cache Match?      │  │
│  │    → YES → return cache    │  │  ← 100% savings
│  │    → NO → continue         │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │ 2. Prefix Optimization     │  │  ← Maximize upstream cache
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │ 3. Prompt Slimming         │  │  ← Reduce token count
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │ 4. Forward to LLM API      │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │ 5. Cache result + stats    │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
    ↓
LLM Provider Response
```

---

## 📊 See Your Savings

```bash
curl http://localhost:8000/v1/usage
```

```json
{
  "summary": {
    "total_calls": 1000,
    "cache_hits": 350,
    "cache_hit_rate": 35.0,
    "total_tokens": 500000,
    "total_tokens_saved": 175000
  }
}
```

---

## 🔌 Supported Providers

| Provider | Status | Notes |
|----------|--------|-------|
| DeepSeek | ✅ Full | Great cache support |
| OpenAI | ✅ Full | GPT-3.5/4/4o |
| Zhipu GLM | ✅ Full | GLM-4 series |
| Qwen (Alibaba) | ✅ Full | Qwen2 series |
| Doubao (Volcengine) | ✅ Full | |
| Anthropic Claude | ✅ Full | |
| Google Gemini | ✅ Full | |
| Any OpenAI-compatible | ✅ Full | Point base_url to Cost Valve |

---

## 🆚 Open Source vs Commercial

| Feature | Open Source | [Cloud SaaS](https://costvalve.cloud) |
|---------|:-----------:|:-------------------------------------:|
| Exact Cache | ✅ | ✅ |
| Prefix Optimization | ✅ | ✅ |
| Prompt Slimming | ✅ | ✅ |
| Usage Stats | ✅ Basic | ✅ Advanced Dashboard |
| **Semantic Cache** | ❌ | ✅ Vector similarity matching |
| **Smart Routing** | ❌ | ✅ Cheapest model auto-selection |
| **Cascade Inference** | ❌ | ✅ Try cheap models first |
| **Multi-Tenant** | ❌ | ✅ Team management |
| **HA Deployment** | ❌ | ✅ Production-grade |
| Support | Community | Dedicated + SLA |

---

## 🗺️ Roadmap

- [ ] Semantic cache (vector similarity)
- [ ] Smart routing across providers
- [ ] Web dashboard with charts
- [ ] Redis cluster support
- [ ] Streaming optimization
- [ ] Rate limiting & budgeting
- [ ] Kubernetes Helm chart

---

## 🤝 Contributing

Contributions are welcome! Feel free to:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a Pull Request

Found a bug? Open an Issue!

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**If this project saves you money, give it a ⭐ Star!**

Made with ❤️ for cost-conscious AI builders.

</div>
