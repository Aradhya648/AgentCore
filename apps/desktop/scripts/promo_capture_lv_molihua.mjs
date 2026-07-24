/**
 * LV 诉茉莉奶白 · promo capture 单入口
 *
 *   node scripts/promo_capture_lv_molihua.mjs full [--tape <id>] [--out <path>]
 *   node scripts/promo_capture_lv_molihua.mjs repair [--preset stills|admit|fixup|patch|rounds] [--only id,…]
 *   node scripts/promo_capture_lv_molihua.mjs speed1-clip [--tape <id>] [--out <path>]
 *
 * Prereq:
 *   cd apps/desktop && $env:VITE_API_URL='http://localhost:8015'; pnpm build:webapp
 *   Backend on PROMO_API with DEMO_TAPE_REPLAY_ENABLED=true
 *
 * Env: PROMO_TAPE / PROMO_OUT / PROMO_API / PROMO_USER / PROMO_PASS / PROMO_PORT / …
 */

import { parseCli, printHelp } from "./promo_lv_molihua/cli.mjs";
import { run as runFull } from "./promo_lv_molihua/cmd/full.mjs";
import { run as runSpeed1 } from "./promo_lv_molihua/cmd/speed1_clip.mjs";
import { run as runRepair } from "./promo_lv_molihua/repair/index.mjs";

async function main() {
  let cli;
  try {
    cli = parseCli(process.argv.slice(2));
  } catch (e) {
    console.error(String(e?.message || e));
    printHelp();
    process.exitCode = 2;
    return;
  }

  if (cli.help || !cli.command) {
    printHelp();
    process.exitCode = cli.help ? 0 : 2;
    return;
  }

  const opts = {
    tape: cli.tape,
    out: cli.out,
    preset: cli.preset,
    only: cli.only,
  };

  if (cli.command === "full") {
    await runFull(opts);
  } else if (cli.command === "repair") {
    await runRepair(opts);
  } else if (cli.command === "speed1-clip") {
    await runSpeed1(opts);
  } else {
    printHelp();
    process.exitCode = 2;
  }
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
