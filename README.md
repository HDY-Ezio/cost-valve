# ⚡ 节能阀 Cost Valve

<div align="center">

**AI API 成本优化网关 —— 不改一行代码，立省 50-90% 调用成本**

[![License: MIT](https://img.shields.io/badge/License-MIT-orange.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-%E5%85%8D%E8%B4%B9%E5%85%AC%E6%B5%8B-brightgreen.svg)]()
[![Uptime](https://img.shields.io/badge/Uptime-99.9%25-blue.svg)]()

**30 秒接入 · 零改造 · 全模型兼容 · 公测免费**

[立即接入](#-30-秒接入) · [在线面板](https://panel.costvalve.cloud) · [API 文档](#-api-参考)

</div>

---

## 🤔 这是什么？

一句话：**架在你的 AI 应用和模型供应商之间的智能代理层。**

你原来调 DeepSeek、OpenAI、通义千问……只需要把 `base_url` 换成节能阀的地址，**代码一个字不用改**。

节能阀自动帮你做三件事：

| 能力 | 效果 |
|------|------|
| 🗄️ 智能缓存 | 相同问题不重复计费，命中缓存直接返回，**省 90%+** |
| 📦 前缀压缩 | 自动合并重复上下文，砍掉冗余 token |
| 📊 用量看板 | 实时显示每次调用花了多少、省了多少 |

> **🎉 当前限时免费：所有功能无限量使用，不收任何费用。**

---

## 🚀 30 秒接入

### 方式一：复制发给你的 AI（最省事）

> 👇 点击代码块右上角复制，完整粘贴给你正在用的 AI 助手，它会自动帮你完成接入。

```
请为我的项目接入「节能阀」API 代理网关。

操作步骤：
1. 注册账户（POST 请求）：
   URL: https://api.costvalve.cloud/api/register
   Headers: Content-Type: application/json
   Body: {"email": "我的邮箱地址", "name": "可选名称"}
   → 返回 api_key，记下来

2. 修改项目的 base_url 为：
   https://api.costvalve.cloud/v1

3. 在每次请求的 headers 中加入：
   Authorization: Bearer {上一步返回的 api_key}
   X-Upstream-Key: {我原来的模型 API 密钥}
   X-Upstream-URL: {我原来的模型 API 地址，如 https://api.deepseek.com}

4. 接入完成后告诉我：「节能阀已接入」

管理面板：https://panel.costvalve.cloud（可查看用量和节省明细）
文档：https://github.com/HDY-Ezio/cost-valve
```

### 方式二：手动改 3 行配置

**改之前：**
```python
base_url = "https://api.deepseek.com/v1"
headers = {"Authorization": "Bearer sk-xxxx"}
```

**改之后：**
```python
base_url = "https://api.costvalve.cloud/v1"
headers = {
    "Authorization": "Bearer 你的节能阀Key",   # 注册后邮件收到
    "X-Upstream-Key": "sk-xxxx",               # 你原来的模型密钥
    "X-Upstream-URL": "https://api.deepseek.com"  # 你原来的模型地址
}
```

就这么多，完事。

---

## 💰 价格

| 项目 | 价格 |
|------|------|
| 免费额度 | 1,000 次/月 |
| 超出后 | ¥0.01/次 |
| 缓存节省 | 平均 90%+ |

> **🎉 公测期间全部免费、无限量使用，不限时。** 后续恢复正式价格会提前通知。

**不碰 token、不付上游费用、只在你省钱后才收费。**

---

## 🤖 支持所有 OpenAI 兼容模型

任何兼容 OpenAI 格式的模型都能直接接入：

| 供应商 | 状态 |
|--------|------|
| DeepSeek | ✅ |
| OpenAI / GPT | ✅ |
| 通义千问 (阿里云) | ✅ |
| 智谱 GLM | ✅ |
| 月之暗面 Kimi | ✅ |
| 百川 | ✅ |
| 其他 OpenAI 兼容 API | ✅ |

只需提供原始模型的 API 地址和密钥，节能阀透明转发，不改变任何行为。

---

## 📊 在线面板

打开 [panel.costvalve.cloud](https://panel.costvalve.cloud) 即可查看：

- 💰 实时余额和当月用量
- 📈 每日调用趋势图
- 🗄️ 缓存命中率 & 节省明细
- 📦 前缀压缩节省统计
- 🔔 余量提醒设置
- 📧 邮箱绑定（找回 Key）

---

## 🏗️ 技术架构

```
┌──────────┐     ┌──────────────────┐     ┌──────────────┐
│ 你的应用  │────▶│   节能阀网关      │────▶│  模型供应商   │
│          │     │                  │     │  DeepSeek    │
│ base_url │     │  • 智能缓存      │     │  OpenAI      │
│ 改一行   │     │  • 前缀压缩      │     │  通义千问    │
│ 就搞定   │     │  • 用量统计      │     │  ...         │
└──────────┘     └──────────────────┘     └──────────────┘
```

- **协议兼容**：完全兼容 OpenAI API 格式，无需修改业务代码
- **高性能**：Python + FastAPI + Cython 编译核心模块
- **数据安全**：API Key SHA256 哈希存储，不保存明文

---

## 📖 API 参考

| 端点 | 说明 |
|------|------|
| `POST /api/register` | 注册（邮箱即账号，Key 邮件发送） |
| `POST /api/recover` | 找回 API Key |
| `POST /v1/chat/completions` | Chat 接口（OpenAI 兼容） |
| `GET /v1/models` | 可用模型列表 |
| `GET /v1/usage` | 用量统计 |
| `GET /v1/savings` | 节省明细 |

**请求头说明：**

| Header | 必填 | 说明 |
|--------|------|------|
| `Authorization` | ✅ | `Bearer {节能阀API-Key}` |
| `X-Upstream-Key` | ✅ | 你原来的模型 API 密钥 |
| `X-Upstream-URL` | ❌ | 模型 API 地址（默认 DeepSeek） |

---

## 📬 联系我们

- 微信：`xingmu_2026`
- 邮箱：hdyabcd@163.com

---

<div align="center">

**[立即接入](#-30-秒接入)** · [在线面板](https://panel.costvalve.cloud) · [GitHub](https://github.com/HDY-Ezio/cost-valve)

<b>节能阀</b> · 花 1 分，省 10 块

</div>
