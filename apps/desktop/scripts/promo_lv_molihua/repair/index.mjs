/**
 * repair subcommand — dispatches to absorbed presets:
 *   stills | admit | fixup | patch | rounds
 */
import { run as admit } from "./admit.mjs";
import { run as fixup } from "./fixup.mjs";
import { run as patch } from "./patch.mjs";
import { run as rounds } from "./rounds.mjs";
import { run as stills } from "./stills.mjs";

const PRESETS = {
  stills,
  admit,
  fixup,
  patch,
  rounds,
};

/**
 * @param {{ tape?: string, out?: string, preset?: string, only?: string }} opts
 */
export async function run(opts = {}) {
  const preset = opts.preset || "stills";
  const fn = PRESETS[preset];
  if (!fn) {
    throw new Error(
      `Unknown repair preset: ${preset} (use: ${Object.keys(PRESETS).join(" | ")})`,
    );
  }
  console.log(`repair preset=${preset}`);
  await fn(opts);
}

export { PRESETS };
