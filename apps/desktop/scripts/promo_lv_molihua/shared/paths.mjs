/**
 * Repo-relative path helpers for lv-molihua promo capture.
 * No absolute machine paths — everything resolves from this file or CLI/env.
 */
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const DEFAULT_TAPE = "lv-molihua-trademark";
export const DEFAULT_OUT_REL = "apps/promo/assets/lv-molihua";

const here = dirname(fileURLToPath(import.meta.url));
/** apps/desktop */
export const desktopDir = resolve(here, "../../..");
/** monorepo root */
export const root = resolve(desktopDir, "../..");
export const distWeb = resolve(desktopDir, "dist-web");

/**
 * @param {{ tape?: string, out?: string }} opts
 */
export function resolveCapturePaths(opts = {}) {
  const tape = opts.tape || process.env.PROMO_TAPE || DEFAULT_TAPE;
  const outArg = opts.out || process.env.PROMO_OUT;
  const outRel =
    outArg ||
    (tape === DEFAULT_TAPE ? DEFAULT_OUT_REL : `apps/promo/assets/${tape}`);
  const outRoot = isAbsolute(outRel) ? resolve(outRel) : resolve(root, outRel);
  return {
    tape,
    outRel,
    outRoot,
    stillsDir: resolve(outRoot, "stills"),
    clipsDir: resolve(outRoot, "clips"),
    sequencesDir: resolve(outRoot, "sequences"),
    videoTmpDir: resolve(outRoot, "_video_tmp"),
    videoTmpSpeed1Dir: resolve(outRoot, "_video_tmp_speed1"),
    speed1SeqDir: resolve(outRoot, "sequences/clip-streaming-debate-speed1"),
  };
}

export function loadCreds() {
  return {
    user: process.env.PROMO_USER ?? "promo_lv",
    pass: process.env.PROMO_PASS ?? "promopass",
    api: (process.env.PROMO_API ?? "http://localhost:8015").replace(/\/$/, ""),
    port: Number(process.env.PROMO_PORT ?? 5174),
  };
}
