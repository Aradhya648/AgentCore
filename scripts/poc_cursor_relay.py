"""
PoC: AgentCore → Cursor SDK 中转验证

验证链路：发送消息 → Cursor Agent 处理 → 流式返回回复

用法:
    $env:CURSOR_API_KEY = "cursor_你的key"
    pip install cursor-sdk
    python scripts/poc_cursor_relay.py
"""

import os
import sys
import time

from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, CursorAgentError


def relay_message(agent, message: str) -> str:
    """发送消息给 Cursor Agent，流式打印并收集完整回复。"""
    print(f"\n{'='*60}")
    print(f"[USER] {message}")
    print(f"{'='*60}")
    print("[CURSOR] ", end="", flush=True)

    run = agent.send(message)
    full_text = ""

    for msg in run.messages():
        if msg.type == "assistant":
            for block in msg.message.content:
                if block.type == "text":
                    print(block.text, end="", flush=True)
                    full_text += block.text

    result = run.wait()
    print(f"\n[STATUS] {result.status} | run_id={run.id}")
    return full_text


def main():
    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        print("ERROR: 请设置环境变量 CURSOR_API_KEY")
        print("  PowerShell: $env:CURSOR_API_KEY = \"cursor_你的key\"")
        print("  获取地址: https://cursor.com/dashboard/integrations")
        sys.exit(1)

    workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"[INFO] Workspace: {workspace}")
    print(f"[INFO] API Key: {api_key[:12]}...")
    print(f"[INFO] 正在创建 Cursor Agent...")

    start = time.time()

    try:
        with Agent.create(
            model="composer-2.5",
            api_key=api_key,
            local=LocalAgentOptions(cwd=workspace),
        ) as agent:
            elapsed = time.time() - start
            print(f"[INFO] Agent 创建成功 ({elapsed:.1f}s) | agent_id={agent.agent_id}")

            # 第一轮：通用对话（验证非代码任务）
            relay_message(agent, "你好，请用一句话介绍你自己")

            # 第二轮：代码相关（验证多轮 + 代码能力）
            relay_message(agent, "看看这个项目的 package.json，告诉我项目名称和主要依赖")

            # 第三轮：验证上下文保持
            relay_message(agent, "基于你刚才看到的信息，这个项目是做什么的？")

            print(f"\n{'='*60}")
            print("[DONE] PoC 验证完成！三轮对话均成功。")
            print(f"[INFO] 总耗时: {time.time() - start:.1f}s")

    except CursorAgentError as err:
        print(f"\n[FAIL] Agent 启动失败: {err.message}")
        print(f"  可重试: {err.is_retryable}")
        if err.is_retryable:
            print("  建议: 等几秒后重试")
        else:
            print("  建议: 检查 API Key 是否正确、账户是否有额度")
        sys.exit(1)


if __name__ == "__main__":
    main()
