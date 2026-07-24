/**
 * PoC: AgentCore → Cursor SDK 中转验证 (TypeScript/Node.js)
 *
 * 验证链路：发送消息 → Cursor Agent 处理 → 流式返回回复
 *
 * 用法:
 *   $env:CURSOR_API_KEY = "crsr_..."
 *   node scripts/poc_cursor_relay.mjs
 */

import { Agent } from "@cursor/sdk";

const apiKey = process.env.CURSOR_API_KEY;
if (!apiKey) {
  console.error("ERROR: 请设置环境变量 CURSOR_API_KEY");
  process.exit(1);
}

const workspace = process.cwd();
console.log(`[INFO] Workspace: ${workspace}`);
console.log(`[INFO] API Key: ${apiKey.slice(0, 12)}...`);
console.log(`[INFO] 正在创建 Cursor Agent...`);

const start = Date.now();

try {
  await using agent = await Agent.create({
    apiKey,
    model: { id: "composer-2.5" },
    local: { cwd: workspace },
  });

  console.log(`[INFO] Agent 创建成功 (${((Date.now() - start) / 1000).toFixed(1)}s) | agent_id=${agent.agentId}`);

  // 辅助函数：发送消息并流式打印回复
  async function relay(message) {
    console.log(`\n${"=".repeat(60)}`);
    console.log(`[USER] ${message}`);
    console.log(`${"=".repeat(60)}`);
    process.stdout.write("[CURSOR] ");

    const run = await agent.send(message);
    let fullText = "";

    for await (const event of run.stream()) {
      if (event.type === "assistant") {
        for (const block of event.message.content) {
          if (block.type === "text") {
            process.stdout.write(block.text);
            fullText += block.text;
          }
        }
      }
    }

    const result = await run.wait();
    console.log(`\n[STATUS] ${result.status} | run_id=${run.id}`);
    return fullText;
  }

  // 第一轮：通用对话
  await relay("你好，请用一句话介绍你自己");

  // 第二轮：代码相关
  await relay("看看这个项目的 package.json，告诉我项目名称");

  // 第三轮：上下文保持
  await relay("基于你刚才看到的信息，这个项目是做什么的？");

  console.log(`\n${"=".repeat(60)}`);
  console.log(`[DONE] PoC 验证完成！三轮对话均成功。`);
  console.log(`[INFO] 总耗时: ${((Date.now() - start) / 1000).toFixed(1)}s`);

} catch (err) {
  console.error(`\n[FAIL] ${err.message}`);
  if (err.isRetryable) {
    console.error("  建议: 等几秒后重试");
  } else {
    console.error("  建议: 检查 API Key 是否正确、账户是否有额度");
  }
  process.exit(1);
}
