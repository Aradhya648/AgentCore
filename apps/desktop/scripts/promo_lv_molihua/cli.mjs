/**
 * CLI parser for promo_capture_lv_molihua.mjs
 *
 *   node scripts/promo_capture_lv_molihua.mjs <full|repair|speed1-clip> [options]
 */

import { DEFAULT_OUT_REL, DEFAULT_TAPE } from "./shared/paths.mjs";

const COMMANDS = ["full", "repair", "speed1-clip"];
const REPAIR_PRESETS = ["stills", "admit", "fixup", "patch", "rounds"];

export function printHelp() {
  console.log(`Usage: node promo_capture_lv_molihua.mjs <command> [options]

Commands:
  full          Director full capture (clean env + seek/speed/acceptance)
  repair        Parameterized still repair / patch / fixup / admit / rounds
  speed1-clip   SPEED=1 streaming clip + sequence frames

Common options:
  --tape <id>          Tape id (default: ${DEFAULT_TAPE}; env PROMO_TAPE)
  --out <path>         Output root, repo-relative or absolute
                       (default: ${DEFAULT_OUT_REL}; env PROMO_OUT)
  --help, -h           Show this help

repair options:
  --preset <name>      ${REPAIR_PRESETS.join("|")}  (default: stills)
  --only <id,id,…>     Limit still ids (stills / rounds presets)

Env (all commands): PROMO_API PROMO_USER PROMO_PASS PROMO_PORT PROMO_SPEED
                    PROMO_GAP PROMO_OVERWRITE PROMO_WIPE PROMO_HEADED
`);
}

/**
 * @param {string[]} argv process.argv.slice(2)
 */
export function parseCli(argv) {
  const out = {
    help: false,
    command: undefined,
    tape: undefined,
    out: undefined,
    preset: undefined,
    only: undefined,
  };

  if (argv.length === 0) {
    out.help = true;
    return out;
  }

  let i = 0;
  const first = argv[0];
  if (first === "--help" || first === "-h") {
    out.help = true;
    return out;
  }
  if (COMMANDS.includes(first)) {
    out.command = first;
    i = 1;
  } else if (first?.startsWith("-")) {
    // allow `… --help` without command
  } else {
    throw new Error(
      `Unknown command: ${first} (use: ${COMMANDS.join(" | ")} | --help)`,
    );
  }

  for (; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--help" || a === "-h") out.help = true;
    else if (a === "--tape") out.tape = argv[++i];
    else if (a?.startsWith("--tape=")) out.tape = a.slice("--tape=".length);
    else if (a === "--out") out.out = argv[++i];
    else if (a?.startsWith("--out=")) out.out = a.slice("--out=".length);
    else if (a === "--preset") out.preset = argv[++i];
    else if (a?.startsWith("--preset=")) out.preset = a.slice("--preset=".length);
    else if (a === "--only") out.only = argv[++i];
    else if (a?.startsWith("--only=")) out.only = a.slice("--only=".length);
    else throw new Error(`Unknown arg: ${a} (see --help)`);
  }

  if (out.preset && !REPAIR_PRESETS.includes(out.preset)) {
    throw new Error(
      `Unknown --preset ${out.preset} (use: ${REPAIR_PRESETS.join(" | ")})`,
    );
  }

  return out;
}

export { COMMANDS, REPAIR_PRESETS };
