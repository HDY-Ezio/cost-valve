# 节能阀 Cost Valve

> 🚰 就像水龙头一样控制你的 AI 成本
>
> 在 AI API 前面加一层智能网关，重复请求直接返回缓存，不用每次烧 token。
> 真实场景省 30%-70%，改一行配置就能用。

---

## ✨ 核心能力

| 能力 | 说明 | 预期降本 |
|------|------|---------|
| **精确缓存** | 完全相同的请求直接返回缓存结果，零 token 消耗 | 20-40% |
| **前缀优化** | 自动整理请求结构，最大化命中上游 LLM 的 prompt cache | 10-30% |
| **Prompt 瘦身** | 去除冗余空白、重复内容，减少输入 token | 5-15% |
| **用量看板** | 实时统计调用量、缓存命中率、节省 token 数 | - |

> 💡 **商业版**额外提供：语义缓存（相同含义不同表述也能命中）、智能路由（选最便宜的模型）、级联推理（从便宜模型逐层尝试）、多租户管理等高级能力。

---

## 🚀 快速开始

### 方式一：Docker 一键启动

```bash
# 1. 克隆项目
git clone https://github.com/HDY-Ezio/cost-valve.git
cd cost-valve

# 2. 配置你的 API Key
cp .env.example .env
# 编辑 .env，填入至少一个模型厂商的 API Key
# 例如：DEEPSEEK_API_KEY=sk-xxxx

# 3. 启动
docker-compose up -d

# 4. 验证
curl http://localhost:8000/health
```

### 方式二：Python 直接运行

```bash
git clone https://github.com/HDY-Ezio/cost-valve.git
cd cost-valve
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入 API Key
python main.py
```

### 方式三：零配置试用

不想配置环境变量？每次请求通过 Header 指定上游即可：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="anything",
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "你好"}],
    extra_headers={
        "X-Upstream-Key": "sk-你的上游Key",
        "X-Upstream-URL": "https://api.deepseek.com",
    }
)

print(response.choices[0].message.content)
```

---

## 🔧 如何接入

**只需改一行：把 base_url 指向节能阀**

```python
# 原来
client = OpenAI(api_key="sk-xxx")

# 现在
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="你的节能阀Key",  # 不设置则无需认证
)
```

完全兼容 OpenAI API 格式，支持所有主流模型厂商。

---

## 🏗️ 架构

```
用户请求 → [节能阀 Cost Valve] → LLM 厂商 API
              ↓
          精确缓存命中？→ 是 → 直接返回，省 100%
              ↓ 否
          前缀优化 → 提高上游缓存命中率
              ↓
          转发到上游模型
              ↓
          结果写入缓存 + 记录用量
```

---

## 📊 查看节省效果

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

- DeepSeek
- OpenAI
- 智谱 GLM
- 通义千问（阿里云百炼）
- 豆包（火山引擎）
- Anthropic Claude
- Google Gemini
- 任何 OpenAI 兼容格式的 API

---

## 🆚 开源版 vs 商业版

| 功能 | 开源版 | 商业版 |
|------|--------|--------|
| 精确缓存 | ✅ | ✅ |
| 前缀优化 | ✅ | ✅ |
| Prompt 瘦身 | ✅ | ✅ |
| 用量统计 | ✅ 基础版 | ✅ 高级看板 |
| 语义缓存 | ❌ | ✅ 向量相似度匹配 |
| 智能路由 | ❌ | ✅ 多模型择优 |
| 级联推理 | ❌ | ✅ 逐层尝试 |
| 多租户管理 | ❌ | ✅ |
| 高可用部署 | ❌ | ✅ |
| 技术支持 | 社区 | 专属支持 + SLA |

> 商业版即开即用 SaaS：[costvalve.cloud](https://costvalve.cloud)

---

## 🤝 贡献

欢迎 Issue 和 PR！

1. Fork 本仓库
2. 创建你的特性分支
3. 提交改动
4. 发起 Pull Request

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)
