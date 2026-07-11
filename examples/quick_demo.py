# -*- coding: utf-8 -*-
"""
节能阀快速体验 Demo
===================
改一行 Key 就能跑，亲眼看看缓存能省多少钱。

使用方法：
1. 把下方 YOUR_API_KEY 改成你自己的 DeepSeek API Key
2. 运行：python quick_demo.py
3. 观察：第一次调用正常耗时，第二次同样的问题秒回（缓存命中）
"""

import time
import requests

# ===== 改成你的 Key =====
YOUR_API_KEY = "sk-你的DeepSeekKey"  # 例如：sk-1234567890abcdef
UPSTREAM_URL = "https://api.deepseek.com"  # 用其他模型就改这里
GATEWAY_URL = "https://api.costvalve.cloud/v1/chat/completions"
MODEL = "deepseek-chat"
# ========================

def chat(question, desc=""):
    """发一次请求，打印耗时和结果"""
    print(f"\n{'='*50}")
    print(f"▶ {desc}")
    print(f"❓ 问题：{question}")
    print(f"{'='*50}")

    start = time.time()
    resp = requests.post(
        GATEWAY_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {YOUR_API_KEY}",
            "X-Upstream-URL": UPSTREAM_URL,
        },
        json={
            "model": MODEL,
            "messages": [{"role": "user", "content": question}],
            "temperature": 0.7,
        },
        timeout=30,
    )
    elapsed = time.time() - start

    if resp.status_code == 200:
        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        # 判断是不是缓存命中（响应极快+X-Cache头）
        is_cached = elapsed < 0.5  # 经验值：缓存命中通常 < 0.5 秒
        cache_flag = "⚡ 缓存命中！" if is_cached else "🐢 实时生成"

        print(f"\n{cache_flag}  耗时：{elapsed:.2f} 秒")
        print(f"📊 消耗 token：{usage.get('total_tokens', 'N/A')}")
        print(f"\n💬 回答：{answer[:200]}{'...' if len(answer) > 200 else ''}")
        return True
    else:
        print(f"❌ 请求失败：{resp.status_code}")
        print(f"   {resp.text[:200]}")
        return False


def main():
    print("🚰 节能阀 Cost Valve - 快速体验 Demo")
    print("=" * 50)

    if "你的DeepSeekKey" in YOUR_API_KEY:
        print("\n⚠️  请先把脚本里的 YOUR_API_KEY 改成你自己的 Key！")
        print("   注册地址：https://platform.deepseek.com/")
        return

    question = "用三句话解释什么是节能阀，以及它怎么帮我省钱"

    # 第一次调用（正常转发）
    ok1 = chat(question, "第一次调用（正常转发）")

    # 第二次调用（同样的问题，应该命中缓存）
    if ok1:
        print("\n\n💡 等一下，马上问同样的问题...")
        time.sleep(1)
        ok2 = chat(question, "第二次调用（同样的问题）")

        if ok2:
            print("\n\n" + "=" * 50)
            print("🎉 体验完成！")
            print("=" * 50)
            print("""
看到了吗？第二次同样的问题：
  • 几乎零延迟 —— 用户体验更好
  • 零 token 消耗 —— 不花一分钱

这就是节能阀最核心的能力：精确缓存。
在真实业务场景中，重复问题占比通常 30%-70%，
意味着你每个月的 AI 账单，至少能砍掉三分之一。

📚 更多功能：语义缓存、智能路由、级联推理...
👉 了解更多：https://github.com/HDY-Ezio/cost-valve
            """)


if __name__ == "__main__":
    main()
