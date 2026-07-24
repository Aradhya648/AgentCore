import { promises as fs } from "node:fs";
import { join, relative } from "node:path";
import type { WorkspaceOpResult } from "@shared/ipc-contract";
import { GREP_MAX_FILES, GREP_MAX_RESULTS_CAP } from "../constants";
import { realInside, resolveLexical, toReason } from "../pathGuard";
import type { StoredRoot } from "../roots";
import { shouldSkipWorkspaceEntry } from "../workspaceIgnore";
import {
  globToRegExp,
  opErr,
  opOk,
  readTextSafe,
  toPosix,
  trimLine,
} from "./result";

export async function opGrep(
  root: StoredRoot,
  args: Record<string, unknown>,
): Promise<WorkspaceOpResult> {
  const pattern = String(args.pattern ?? "");
  const directory = String(args.directory ?? ".");
  const glob = args.glob ? String(args.glob) : "";
  const caseInsensitive = Boolean(args.case_insensitive);
  const filesOnly = Boolean(args.files_only);
  const maxResults = Math.max(
    1,
    Math.min(Number(args.max_results ?? 50), GREP_MAX_RESULTS_CAP),
  );

  const baseAbs = resolveLexical(root, directory);
  if (!baseAbs) return opErr("OutsideWorkspace", directory);
  const baseReal = await realInside(root, baseAbs);
  if (!baseReal.ok) {
    return baseReal.code === "out_of_root"
      ? opErr("OutsideWorkspace", directory)
      : opErr("PathNotFound", directory);
  }
  let baseIsFile = false;
  try {
    const st = await fs.stat(baseReal.path);
    baseIsFile = st.isFile();
    if (!st.isDirectory() && !st.isFile()) {
      return opErr("PathNotFound", directory);
    }
  } catch {
    return opErr("PathNotFound", directory);
  }

  let re: RegExp;
  try {
    re = new RegExp(pattern, caseInsensitive ? "i" : "");
  } catch (e) {
    return opErr("WorkspaceIOError", `非法正则：${toReason(e)}`);
  }
  const nameRe = glob ? globToRegExp(glob) : null;

  const hits: { path: string; line_no: number; text: string }[] = [];
  const fileCounts: [string, number][] = [];
  let totalMatches = 0;
  let truncated = false;
  let filesScanned = 0;
  let stop = false;

  // Scan one file's lines into the accumulators; return true if a result cap is
  // hit. Shared by the single-file fast path and the directory walk so both
  // render identical hits / counts / truncation (mirrors ServerWorkspace).
  const scanFile = async (absFile: string): Promise<boolean> => {
    const text = await readTextSafe(absFile);
    if (text === null) return false; // binary / too large / unreadable — skip
    const rel = toPosix(relative(root.absPath, absFile));
    let fileCount = 0;
    let stopLocal = false;
    const lines = text.split("\n");
    for (let i = 0; i < lines.length; i++) {
      if (!re.test(lines[i])) continue;
      fileCount++;
      totalMatches++;
      if (!filesOnly) {
        hits.push({ path: rel, line_no: i + 1, text: trimLine(lines[i]) });
        if (hits.length >= maxResults) {
          truncated = true;
          stopLocal = true;
          break;
        }
      }
    }
    if (fileCount > 0) {
      fileCounts.push([rel, fileCount]);
      if (filesOnly && fileCounts.length >= maxResults) {
        truncated = true;
        stopLocal = true;
      }
    }
    return stopLocal;
  };

  // `directory` may name a single file (rg PATTERN FILE): scan just it, no walk.
  // `glob` is moot — the file is already pinpointed.
  if (baseIsFile) {
    await scanFile(baseReal.path);
    return opOk({
      hits,
      file_counts: fileCounts,
      total_matches: totalMatches,
      truncated,
    });
  }

  const walk = async (absDir: string): Promise<void> => {
    if (stop) return;
    let dirents: import("node:fs").Dirent[];
    try {
      dirents = await fs.readdir(absDir, { withFileTypes: true });
    } catch {
      return;
    }
    dirents.sort((a, b) => a.name.localeCompare(b.name));
    for (const d of dirents) {
      if (stop) break;
      if (!d.isFile()) continue;
      if (shouldSkipWorkspaceEntry(d.name, false)) continue;
      if (nameRe && !nameRe.test(d.name)) continue;
      filesScanned++;
      if (filesScanned > GREP_MAX_FILES) {
        truncated = true;
        stop = true;
        break;
      }
      stop = await scanFile(join(absDir, d.name));
      if (stop) break;
    }
    if (stop) return;
    for (const d of dirents) {
      if (stop) break;
      if (d.isDirectory() && !shouldSkipWorkspaceEntry(d.name, true)) {
        await walk(join(absDir, d.name));
      }
    }
  };

  await walk(baseReal.path);
  return opOk({
    hits,
    file_counts: fileCounts,
    total_matches: totalMatches,
    truncated,
  });
}
