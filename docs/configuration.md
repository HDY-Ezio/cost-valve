# 配置说明

所有配置通过环境变量设置，支持 `.env` 文件。

## 基础配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `APP_HOST` | `0.0.0.0` | 监听地址 |
| `APP_PORT` | `8000` | 监听端口 |
| `APP_DEBUG` | `false` | 调试模式（开启后有 API 文档） |
| `DB_PATH` | `./data/cost_valve.db` | SQLite 数据库路径 |
| `COST_VALVE_API_KEY` | 自动生成 | 访问密钥，不设则自动生成一个 |

## 缓存配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `CACHE_ENABLED` | `true` | 是否启用精确缓存 |
| `EXACT_CACHE_TTL` | `3600` | 精确缓存过期时间（秒） |

## Prompt 优化配置

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `PROMPT_OPTIMIZE_ENABLED` | `true` | 是否启用 Prompt 瘦身 |
| `PROMPT_MAX_TOKENS` | `4096` | 最大 token 数限制 |

## 模型厂商配置

配置对应厂商的 API Key 后，即可直接使用，无需每次请求传入 Header。

| 厂商 | API Key 环境变量 | Base URL 环境变量 | 模型环境变量 |
|------|-----------------|------------------|-------------|
| DeepSeek | `DEEPSEEK_API_KEY` | `DEEPSEEK_BASE_URL` | `DEEPSEEK_MODEL` |
| OpenAI | `OPENAI_API_KEY` | `OPENAI_BASE_URL` | `OPENAI_MODEL` |
| 智谱 GLM | `GLM_API_KEY` | `GLM_BASE_URL` | `GLM_MODEL` |
| 通义千问 | `ALIYUN_API_KEY` | `ALIYUN_BASE_URL` | `ALIYUN_MODEL` |
| 豆包 | `DOUBAO_API_KEY` | `DOUBAO_BASE_URL` | `DOUBAO_MODEL` |
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` | `ANTHROPIC_MODEL` |
| Google Gemini | `GOOGLE_API_KEY` | `GOOGLE_BASE_URL` | `GOOGLE_MODEL` |
| 通用兼容 | `GENERIC_API_KEY` | `GENERIC_BASE_URL` | `GENERIC_MODEL` |
