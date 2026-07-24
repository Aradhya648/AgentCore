/** One-shot smoke: launch the packaged win-unpacked exe and verify a window mounts. */
import { readFileSync } from "node:fs";
import os from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { _electron as electron } from "playwright";

const desktopDir = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const version = JSON.parse(
  readFileSync(join(desktopDir, "package.json"), "utf8"),
).version;
const exe = join(desktopDir, `release/${version}/win-unpacked/AgentCore.exe`);
const userData = join(os.tmpdir(), `agentcore-packaged-smoke-${Date.now()}`);

const app = await electron.launch({
  executablePath: exe,
  args: [`--user-data-dir=${userData}`],
  timeout: 60_000,
});
try {
  const win = await app.firstWindow();
  await win.waitForLoadState("domcontentloaded", { timeout: 30_000 });
  console.log("TITLE:", await win.title());
  console.log("URL:", win.url());
  await win.waitForTimeout(2000);
  const hasInput = await win
    .getByPlaceholder("输入消息…")
    .isVisible()
    .catch(() => false);
  const hasLogin = await win
    .getByText("登录", { exact: true })
    .first()
    .isVisible()
    .catch(() => false);
  console.log("CHAT_INPUT_VISIBLE:", hasInput);
  console.log("LOGIN_SCREEN:", hasLogin);
  if (!hasInput && !hasLogin) {
    const preview = (
      await win
        .locator("body")
        .innerText()
        .catch(() => "")
    ).slice(0, 300);
    console.log("BODY:", preview.replace(/\s+/g, " "));
    throw new Error("expected login screen or chat input");
  }
  console.log("PACKAGED_LAUNCH_OK");
} finally {
  await app.close();
}
