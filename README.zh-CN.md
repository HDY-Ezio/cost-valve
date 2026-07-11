<div align="center">

# 💸 节能阀 Cost Valve — AI API 成本优化网关

**一行配置接入，API 费用直降 30%-70%，零代码改造**

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-一键部署-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Stars](https://img.shields.io/github/stars/HDY-Ezio/cost-valve?style=social)](https://github.com/HDY-Ezio/cost-valve/stargazers)

**[English](README.md) | [中文](README.zh-CN.md)**

---

</div>

## 🎯 为什么需要节能阀？

每个用 AI 的团队都在烧 API 费——同样的问题被问几百遍，每一遍都要全价付 token 钱。

**节能阀架在你的应用和大模型之间，自动拦截重复请求，省下的每一分都是纯利润。**

```
之前：应用 → 大模型API（每次都花钱）
现在：应用 → 节能阀 → 大模型API（命中缓存=免费）
```

### ✨ 真实效果

- **降本 30%-70%**（实测数据，取决于业务场景）
- **一行接入** — 只需改 base_url
- **零学习成本** — 完全兼容 OpenAI API 格式
- **实时看板** — 省了多少钱一目了然

---

## ⚡ 核心功能

| 功能 | 说明 | 降本幅度 |
|------|------|---------|
| 🎯 **精确缓存** | 完全相同的请求直接返回缓存结果 | 20-40% |
| 🧠 **前缀优化** | 自动整理请求结构，最大化上游模型的 prompt cache 命中率 | 10-30% |
| ✂️ **Prompt 瘦身** | 去除冗余空白、重复内容，减少输入 token | 5-15% |
| 📊 **用量看板** | 实时统计：调用量、缓存命中率、节省 token 数 | - |
| 🔌 **多厂商支持** | DeepSeek、OpenAI、通义千问、智谱、豆包、Claude、Gemini | - |
| 🐳 **Docker 部署** | docker-compose 一行命令启动 | - |

---

## 🚀 快速开始

### 方式一：Docker 一键启动（推荐）

```bash
git clone https://github.com/HDY-Ezio/cost-valve.git
cd cost-valve
cp .env.example .env
# 编辑 .env，填入你的 API Key
docker-compose up -d
```

### 方式二：Python 直接运行

```bash
git clone https://github.com/HDY-Ezio/cost-valve.git
cd cost-valve
pip install -r requirements.txt
cp .env.example .env
python main.py
```

### 方式三：零配置试用

不用配置环境变量，每次请求通过 Header 指定上游：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="随便填",
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "你好"}],
    extra_headers={
        "X-Upstream-Key": "sk-你的上游Key",
        "X-Upstream-URL": "https://api.deepseek.com",
    }
)
```

---

## 🔧 工作原理

```
用户请求
    ↓
┌─────────────────────────────────┐
│       节能阀 Cost Valve           │
│  ┌───────────────────────────┐  │
│  │ 1. 精确缓存匹配？           │  │
│  │    → 命中 → 直接返回缓存    │  │  ← 省 100%
│  │    → 未命中 → 继续         │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │ 2. 前缀优化                │  │  ← 提升上游缓存命中率
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │ 3. Prompt 瘦身             │  │  ← 减少 token 数量
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │ 4. 转发到大模型 API         │  │
│  └───────────────────────────┘  │
│  ┌───────────────────────────┐  │
│  │ 5. 结果写入缓存 + 统计      │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
    ↓
大模型返回结果
```

---

## 📊 查看省钱效果

```bash
curl http://localhost:8000/v1/usage
```

返回示例：
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

## 🔌 支持的模型厂商

| 厂商 | 状态 | 说明 |
|------|------|------|
| DeepSeek | ✅ 完整支持 | 缓存效果最佳 |
| OpenAI | ✅ 完整支持 | GPT-3.5/4/4o |
| 智谱 GLM | ✅ 完整支持 | GLM-4 系列 |
| 通义千问 | ✅ 完整支持 | Qwen2 系列 |
| 豆包（火山引擎） | ✅ 完整支持 | |
| Anthropic Claude | ✅ 完整支持 | |
| Google Gemini | ✅ 完整支持 | |
| 任意 OpenAI 兼容 API | ✅ 完整支持 | 修改 base_url 即可 |

---

## 🆚 开源版 vs 商业版

| 功能 | 开源版 | [云端 SaaS 版](https://costvalve.cloud) |
|------|:-----:|:---------------------------------------:|
| 精确缓存 | ✅ | ✅ |
| 前缀优化 | ✅ | ✅ |
| Prompt 瘦身 | ✅ | ✅ |
| 用量统计 | ✅ 基础版 | ✅ 高级看板 |
| **语义缓存** | ❌ | ✅ 向量相似度匹配 |
| **智能路由** | ❌ | ✅ 自动选最便宜模型 |
| **级联推理** | ❌ | ✅ 便宜模型先试 |
| **多租户管理** | ❌ | ✅ 团队协作 |
| **高可用部署** | ❌ | ✅ 生产级 |
| 技术支持 | 社区 | 专属支持 + SLA |

---

## 🗺️ 路线图

- [ ] 语义缓存（向量相似度匹配）
- [ ] 多厂商智能路由
- [ ] 可视化看板（Web UI）
- [ ] Redis 集群支持
- [ ] 流式输出优化
- [ ] 速率限制与预算控制
- [ ] Kubernetes Helm 包

---

## 🤝 贡献代码

欢迎提交 Issue 和 PR！

1. Fork 本仓库
2. 创建你的特性分支
3. 提交改动
4. 发起 Pull Request

发现 Bug？直接提 Issue！

---

## 📄 许可证

MIT License — 详见 [LICENSE](LICENSE)

---

<div align="center">

**如果帮你省钱了，点个 ⭐ Star 支持一下！**

用 ❤️ 为每一个精打细算的 AI 团队打造。

</div>
