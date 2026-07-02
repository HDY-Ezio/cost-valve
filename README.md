# ⚡ 节能阀

**AI 调用成本优化代理 —— 花 1 分钱，省 10 块钱**

---

## 这是什么？

节能阀是一个 API 代理层（纯阀门），架在你的 AI 应用和模型供应商之间。

你原来调 DeepSeek、OpenAI、通义千问，只需要把 `base_url` 改成节能阀的地址，**代码一个字不用改**。

节能阀自动帮你做三件事：
- **缓存优化**：相同问题不重复计费，命中缓存直接返回
- **前缀压缩**：自动合并重复上下文，砍掉冗余 token
- **用量看板**：实时显示你省了多少钱

**每次调用只收 ¥0.01 过路费，每月免费 1000 次。**

---

## 30 秒接入

### 方式一：发给你的 AI（推荐）

把下面这段话完整复制，粘贴给你正在用的 AI 智能体：

```
请为我的 AI 应用接入「节能阀」API 代理。

步骤：
1. 用这个地址注册账户（如果已有账户跳过）：
   POST https://api.costvalve.cloud/api/register
   Content-Type: application/json
   Body: {"email": "我的邮箱", "name": "可选名称"}

2. 把项目的 base_url 改为：https://api.costvalve.cloud/v1

3. 在请求头加上：
   Authorization: Bearer {注册返回的api_key}
   X-Upstream-Key: 我原来的模型API密钥
   X-Upstream-URL: 我原来的模型API地址

4. 接好后告诉我：节能阀已接入，API Key 是 xxx，
   面板地址 https://panel.costvalve.cloud
```

### 方式二：手动改 3 行配置

```python
# 原来
base_url = "https://api.deepseek.com/v1"
headers = {"Authorization": "Bearer sk-xxxx"}

# 改成
base_url = "https://api.costvalve.cloud/v1"
headers = {
    "Authorization": "Bearer 你的节能阀API-Key",
    "X-Upstream-Key": "sk-xxxx",
    "X-Upstream-URL": "https://api.deepseek.com"
}
```

就这么多。完事。

---

## 价格

| 项目 | 价格 |
|------|------|
| 免费额度 | 1000 次/月 |
| 超出后 | ¥0.01/次 |
| 缓存节省 | 平均 90%+ |

**不碰 token，不付上游费用，只收过路费。**

---

## 支持什么模型？

任何 OpenAI 兼容格式的模型都能用：
- DeepSeek
- OpenAI / GPT
- 通义千问
- 智谱 GLM
- 月之暗面 Kimi
- 百川
- ...

你只需要提供原始模型的 API 地址和密钥，节能阀透明转发。

---

## 面板功能

- 📊 实时余额和用量
- 💰 节省看板（缓存命中、前缀优化各省了多少）
- 📧 邮箱绑定（找回 Key 用）
- 🔔 余量提醒
- 📅 每日趋势

面板地址：https://panel.costvalve.cloud

---

## 技术架构

```
你的应用 → 节能阀 → 模型供应商
              ↓
         缓存层（精确匹配 + 语义匹配）
         前缀优化器（自动压缩重复上下文）
         路由层（多供应商适配）
```

- Python + FastAPI
- SQLite 持久化
- Cython 编译核心模块（二进制部署）
- 开源协议：MIT

---

## 联系我们

微信：xingmu_2026

---

<p align="center">
  <b>节能阀</b> · 花 1 分，省 10 块
</p>
