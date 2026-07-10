# 快速上手指南

3 分钟跑起节能阀，立刻开始省钱。

## 前置条件

- Python 3.10+
- 任意一家 LLM 厂商的 API Key（DeepSeek、OpenAI、智谱等）

## 方式一：Docker 部署（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/HDY-Ezio/cost-valve.git
cd cost-valve

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key，例如：
# DEEPSEEK_API_KEY=sk-xxxx

# 3. 启动
docker-compose up -d

# 4. 验证
curl http://localhost:8000/health
```

## 方式二：手动安装

```bash
git clone https://github.com/HDY-Ezio/cost-valve.git
cd cost-valve
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入你的 API Key
python main.py
```

## 你的第一个请求

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-used",  # 本地模式可不设
)

# 如果配置了 DEEPSEEK_API_KEY 环境变量：
response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "你好"}]
)

print(response.choices[0].message.content)
```

## 查看省了多少钱

```bash
curl http://localhost:8000/v1/usage
```
