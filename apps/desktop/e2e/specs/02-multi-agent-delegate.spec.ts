import { expect, test } from "@playwright/test";
import {
  ensureAuthed,
  expectHashConversation,
  openWebapp,
  scriptPrompt,
  sendPrompt,
  waitTurnSettled,
} from "../helpers/app";

/**
 * Case 2 — 多 Agent 派单：发送 → 任务卡/协作图出现 → 打开画布 → 返回。
 * 向量：`multi_agent_delegate`
 */
test("多 Agent 派单：协作图节点可见并可进画布返回", async ({ page }) => {
  await openWebapp(page);
  await ensureAuthed(page);

  await sendPrompt(
    page,
    scriptPrompt("multi_agent_delegate", "请安排团队调研并撰写"),
  );
  await expectHashConversation(page);

  // Status strip / inline graph surfaces once runs start.
  await expect(
    page.getByRole("button", { name: "在画布打开" }),
  ).toBeVisible({ timeout: 30_000 });

  // Graph auto-expands while running; assert xyflow nodes.
  await expect(page.locator(".react-flow__node").first()).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole("button", { name: "在画布打开" }).click();
  await expect
    .poll(() => page.evaluate(() => window.location.hash))
    .toMatch(/\/turn\//);

  await page.goBack();
  await expect
    .poll(() => page.evaluate(() => window.location.hash))
    .toMatch(/#\/conversations\/[a-f0-9]+$/);

  await waitTurnSettled(page);
});
