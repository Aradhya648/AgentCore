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
 * Case 4 — 新建对话与会话切换：新建 → 草稿态 → 再发送。
 * 复用用例 1 向量；钉 `switchConversation(null)` 一族。
 */
test("新建对话：回到草稿后再发送形成新会话", async ({ page }) => {
  await openWebapp(page);
  await ensureAuthed(page);

  await sendPrompt(
    page,
    scriptPrompt("single_agent_text", "第一轮会话"),
  );
  const firstId = await expectHashConversation(page);
  await waitTurnSettled(page);
  await expect(page.getByText("你好，世界！")).toBeVisible();

  await page.getByRole("button", { name: "新对话" }).click();
  // Draft route: hash becomes `#/` or empty conversations path without id.
  await expect
    .poll(() => page.evaluate(() => window.location.hash))
    .toMatch(/#\/?$/);
  await expect(page.getByPlaceholder(/输入消息/)).toBeVisible();

  await sendPrompt(
    page,
    scriptPrompt("single_agent_text", "第二轮新草稿"),
  );
  const secondId = await expectHashConversation(page);
  expect(secondId).not.toBe(firstId);

  await waitTurnSettled(page);
  await expect(page.getByText("你好，世界！")).toBeVisible();
});
