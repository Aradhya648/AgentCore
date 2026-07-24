import { promises as fs } from "node:fs";
import type { WorkspaceOpResult } from "@shared/ipc-contract";
import { GREP_MAX_LINE, WORKSPACE_READ_MAX } from "../constants";

export function opOk(value: unknown): WorkspaceOpResult {
  return { ok: true, value };
}

export function opErr(
  kind: string,
  detail = "",
  count?: number,
): WorkspaceOpResult {
  return {
    ok: false,
    error: count === undefined ? { kind, detail } : { kind, detail, count },
  };
}

export function toPosix(p: string): string {
  return p.split("\\").join("/");
}

/** glob → 锚定正则：`**`=任意（含 /），`*`=非 / 段，`?`=单个非 /，其余字面转义。 */
export function globToRegExp(glob: string): RegExp {
  let re = "";
  for (let i = 0; i < glob.length; i++) {
    const c = glob[i];
    if (c === "*") {
      if (glob[i + 1] === "*") {
        re += ".*";
        i++;
      } else {
        re += "[^/]*";
      }
    } else if (c === "?") {
      re += "[^/]";
    } else {
      re += c.replace(/[.+^${}()|[\]\\]/g, "\\$&");
    }
  }
  return new RegExp(`^${re}$`);
}

export function trimLine(line: string): string {
  const s = line.trim();
  return s.length > GREP_MAX_LINE ? `${s.slice(0, GREP_MAX_LINE)} …` : s;
}

/** 读为 UTF-8 文本；二进制 / 过大 / 不可读则返回 null（grep 跳过）。 */
export async function readTextSafe(abs: string): Promise<string | null> {
  try {
    const st = await fs.stat(abs);
    if (st.size > WORKSPACE_READ_MAX) return null;
    const buf = await fs.readFile(abs);
    if (buf.includes(0)) return null;
    return buf.toString("utf-8");
  } catch {
    return null;
  }
}
