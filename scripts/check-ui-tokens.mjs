#!/usr/bin/env node
/**
 * Shared UI token lint gate (color-tokens.mdc).
 *
 * Usage:
 *   node scripts/check-ui-tokens.mjs --src apps/desktop/src/renderer
 *   node scripts/check-ui-tokens.mjs --src apps/mobile/src
 */
import { readdir, readFile } from "node:fs/promises";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "..");

/** @type {{ id: string; re: RegExp; hint: string }[]} */
const BASE_RULES = [
  {
    id: "rounded-md",
    re: /\brounded-md\b/,
    hint: "use rounded-lg (small) or rounded-xl (large)",
  },
  {
    id: "rounded-sm",
    re: /\brounded-sm\b/,
    hint: "use rounded-lg",
  },
  {
    id: "rounded-2xl",
    re: /\brounded-2xl\b/,
    hint: "use rounded-xl (max large radius)",
  },
  {
    id: "custom-font-px",
    re: /\btext-\[(?:10|11|13)px\]/,
    hint: "use text-xs (12px) or text-sm (14px)",
  },
  {
    id: "tailwind-palette",
    re: /\b(?:bg|text|border|ring|from|to|via)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d+/,
    hint: "use semantic tokens (primary, success, warning, …)",
  },
  {
    id: "arbitrary-hex",
    re: /\b(?:bg|text|border)-\[#[0-9a-fA-F]+\]/,
    hint: "use semantic CSS variables / Tailwind token classes",
  },
];

function parseArgs(argv) {
  let src = "";
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === "--src" && argv[i + 1]) {
      src = argv[++i];
    }
  }
  if (!src) {
    console.error("usage: check-ui-tokens.mjs --src <directory>");
    process.exit(2);
  }
  return { srcDir: join(ROOT, src) };
}

async function walk(dir) {
  /** @type {string[]} */
  const out = [];
  for (const name of await readdir(dir, { withFileTypes: true })) {
    const p = join(dir, name.name);
    if (name.isDirectory()) {
      if (name.name === "node_modules" || name.name === "out" || name.name === "dist") continue;
      out.push(...(await walk(p)));
    } else if (/\.(tsx|ts|css)$/.test(name.name)) {
      out.push(p);
    }
  }
  return out;
}

const { srcDir } = parseArgs(process.argv);
const rules = BASE_RULES;

/** @type {{ file: string; line: number; rule: string; hint: string; text: string }[]} */
const violations = [];

for (const file of await walk(srcDir)) {
  const content = await readFile(file, "utf8");
  const lines = content.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const rule of rules) {
      if (rule.re.test(line)) {
        violations.push({
          file: relative(ROOT, file),
          line: i + 1,
          rule: rule.id,
          hint: rule.hint,
          text: line.trim().slice(0, 120),
        });
      }
    }
  }
}

if (violations.length === 0) {
  console.log(`check-ui-tokens: OK (${relative(ROOT, srcDir)})`);
  process.exit(0);
}

console.error(`check-ui-tokens: ${violations.length} violation(s)\n`);
for (const v of violations) {
  console.error(`${v.file}:${v.line} [${v.rule}] ${v.hint}`);
  console.error(`  ${v.text}\n`);
}
process.exit(1);
