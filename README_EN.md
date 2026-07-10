# Cost Valve

> 🚰 Control your AI costs like a water faucet
>
> A smart gateway layer in front of your AI API. Cached queries return instantly, no tokens burned.
> Save 30-70% in real scenarios with just one line of config change.

---

## ✨ Features

| Feature | Description | Expected Savings |
|---------|-------------|-----------------|
| **Exact Cache** | Identical requests return from cache, zero token cost | 20-40% |
| **Prefix Optimization** | Auto-organize request structure to maximize upstream prompt cache hits | 10-30% |
| **Prompt Slimming** | Remove redundant whitespace and duplicates, reduce input tokens | 5-15% |
| **Usage Dashboard** | Real-time stats: calls, cache hit rate, tokens saved | - |

> 💡 **Pro version** adds: Semantic cache (similar meaning hits even with different wording), intelligent routing (pick cheapest model), cascading inference (try cheaper models first), multi-tenant management, and more.

---

## 🚀 Quick Start

### Docker (Recommended)

```bash
git clone https://github.com/HDY-Ezio/cost-valve.git
cd cost-valve
cp .env.example .env
# Edit .env, add your API key (e.g. DEEPSEEK_API_KEY=sk-xxx)
docker-compose up -d
curl http://localhost:8000/health
```

### Python

```bash
git clone https://github.com/HDY-Ezio/cost-valve.git
cd cost-valve
pip install -r requirements.txt
cp .env.example .env
python main.py
```

---

## 🔧 Usage

Just change your `base_url` to point at Cost Valve:

```python
from openai import OpenAI

# Before
client = OpenAI(api_key="sk-xxx")

# After
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-cost-valve-key",
)
```

Fully OpenAI-compatible, works with all major LLM providers.

---

## 📊 Check Savings

```bash
curl http://localhost:8000/v1/usage
```

---

## 🔌 Supported Providers

DeepSeek, OpenAI, Anthropic, Google Gemini, Zhipu GLM, Qwen (Alibaba), Doubao (Volcengine), and any OpenAI-compatible API.

---

## 🆚 Open Source vs Pro

| Feature | Open Source | Pro |
|---------|-------------|-----|
| Exact Cache | ✅ | ✅ |
| Prefix Optimization | ✅ | ✅ |
| Prompt Slimming | ✅ | ✅ |
| Usage Stats | ✅ Basic | ✅ Advanced |
| Semantic Cache | ❌ | ✅ |
| Intelligent Routing | ❌ | ✅ |
| Cascading Inference | ❌ | ✅ |
| Multi-tenant | ❌ | ✅ |
| HA Deployment | ❌ | ✅ |
| Support | Community | Dedicated + SLA |

> Pro SaaS: [costvalve.cloud](https://costvalve.cloud)

---

## 📄 License

MIT License - see [LICENSE](LICENSE)
