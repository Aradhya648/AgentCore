import { expect, test } from "@playwright/test";
import {
  ensureAuthed,
  expectHashConversation,
  openWebapp,
  scriptPrompt,
  sendPrompt,
  waitTurnSettled,
} from "../helpers/app";
import { HYDRATE_FAIL_CONV_ID } from "../mock/rest";

/**
 * 防回归：本轮已修关键路径（诚实壳层 hydrate 失败 + 打开辩论室深链）。
 *
 * 断流重连横幅「重连」：mock 无法稳定模拟 live rejoin 掉线，单测已钉
 * RetryBanner；此处跳过（缺口见报告）。
 */
test.describe("防回归：hydrate 失败 + 辩论室入口", () => {
  test("对话 hydrate 失败：失败态 + 可重试，禁止静默空白", async ({
    page,
  }) => {
    await openWebapp(page);
    await ensureAuthed(page);

    await page.goto(
      `/index.webapp.html#/conversations/${HYDRATE_FAIL_CONV_ID}`,
      { waitUntil: "domcontentloaded" },
    );

    await expect(page.getByRole("alert")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("对话加载失败")).toBeVisible();
    const retry = page.getByRole("button", { name: "重试" });
    await expect(retry).toBeVisible();

    // Retry re-enters loading then lands on the same honest error (fixture always 500).
    await retry.click();
    await expect(page.getByText("对话加载失败")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByRole("button", { name: "重试" })).toBeVisible();

    // Honest shell covers the pane (z-30); must not read as a blank sendable draft.
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByText("正在加载对话…")).toHaveCount(0);
  });

  test("打开辩论室：URL 含 view=debate，落辩论室而非先闪协作图", async ({
    page,
  }) => {
    await openWebapp(page);
    await ensureAuthed(page);

    await page.getByRole("button", { name: "新对话" }).click();
    await expect(page.getByPlaceholder(/输入消息/)).toBeVisible();

    await sendPrompt(
      page,
      scriptPrompt("multi_agent_debate", "请发起一场正反辩论"),
    );
    await expectHashConversation(page);

    const openDebate = page.getByRole("button", { name: "打开辩论室" });
    await expect(openDebate).toBeVisible({ timeout: 60_000 });
    await openDebate.click();

    await expect
      .poll(() => page.evaluate(() => window.location.hash), {
        timeout: 20_000,
      })
      .toMatch(/view=debate/);

    // Debate tab selected; graph tab must not be the active pressed control.
    const debateTab = page.getByRole("button", { name: "辩论室" });
    await expect(debateTab).toHaveAttribute("aria-pressed", "true");
    await expect(
      page.getByRole("button", { name: "协作图" }),
    ).toHaveAttribute("aria-pressed", "false");

    await waitTurnSettled(page);
  });
});
