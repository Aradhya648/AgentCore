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
 * Case 1 — 草稿首发：输入 → 发送 → URL 跳 `#/conversations/:id` → 流式正文完成。
 * 钉住：MessageInput unmount 不得中断 POST（navigate 后仍流完）。
 */
test("草稿首发：跳转会话 URL 且正文流式完成", async ({ page }) => {
  await openWebapp(page);
  await ensureAuthed(page);

  await sendPrompt(
    page,
    scriptPrompt("single_agent_text", "你好，请打个招呼"),
  );

  const convId = await expectHashConversation(page);
  expect(convId.length).toBeGreaterThan(8);

  await waitTurnSettled(page);
  await expect(page.getByText("你好，世界！")).toBeVisible({ timeout: 15_000 });
});
