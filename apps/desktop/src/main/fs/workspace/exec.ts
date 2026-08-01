import { spawn } from "node:child_process";
import { promises as fs, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import type { WorkspaceOpResult } from "@shared/ipc-contract";
import { EXEC_CAPTURE_CAP, EXEC_LANGS, EXEC_TIMEOUT_CAP_S } from "../constants";
import { realInside, resolveLexical, toReason } from "../pathGuard";
import type { StoredRoot } from "../roots";
import { getRoot } from "../roots";
import {
  decodePipeChunk,
  launcherMissingStderr,
  resolveBashLauncher,
  whichCommand,
} from "./execCodec";
import { opErr, opOk } from "./result";

/** ExecutionResult 形状的成功信封（success 可为 false——执行「跑完了但非 0 退出」）。 */
function execResult(value: {
  success: boolean;
  stdout: string;
  stderr: string;
  exit_code: number;
  duration_ms: number;
}): WorkspaceOpResult {
  return opOk(value);
}

/** Layout dirs auto-prepended to PYTHONPATH (mirrors server ``default_pythonpath_rels``). */
const PYTHONPATH_AUTO_EXTRA = ["src", "lib"] as const;

/**
 * D11′: workspace ``.`` + existing ``src``/``lib`` for local ``code_execute``,
 * same resolution as server ``merge_pythonpath_into_env`` (auto mode).
 */
export function buildWorkspacePythonpathEnv(
  cwdAbs: string,
  prevPythonpath?: string,
): Record<string, string> {
  const entries: string[] = [cwdAbs];
  for (const name of PYTHONPATH_AUTO_EXTRA) {
    const p = join(cwdAbs, name);
    if (existsSync(p)) entries.push(p);
  }
  const prev = prevPythonpath ?? process.env.PYTHONPATH ?? "";
  const merged = [...entries, prev].filter(Boolean).join(delimiter);
  return { PYTHONPATH: merged };
}

/**
 * W3: build ``AGENTCORE_EXTERNAL_<ALIAS>`` env map from ``external_roots``.
 * Only injects roots that are sessionOnly grants bound to ``conversationId``.
 */
export function buildExternalEnvFromRoots(
  externalRoots: Record<string, unknown> | null | undefined,
  conversationId: string,
  lookup: (rootId: string) => StoredRoot | undefined = getRoot,
): Record<string, string> {
  const envExtra: Record<string, string> = {};
  if (!externalRoots || typeof externalRoots !== "object" || !conversationId) {
    return envExtra;
  }
  for (const [alias, rootId] of Object.entries(externalRoots)) {
    const rid = String(rootId ?? "");
    const er = rid ? lookup(rid) : undefined;
    if (
      !er?.absPath ||
      !er.sessionOnly ||
      er.conversationId !== conversationId
    ) {
      continue;
    }
    // Organize mounts must NOT inject AGENTCORE_EXTERNAL_* (proposal §五).
    const mode = er.mode ?? (er.readonly ? "readonly" : undefined);
    if (mode === "organize") continue;
    const safe =
      alias
        .replace(/[^A-Za-z0-9]+/g, "_")
        .replace(/^_|_$/g, "")
        .toUpperCase() || "FOLDER";
    envExtra[`AGENTCORE_EXTERNAL_${safe}`] = er.absPath;
  }
  return envExtra;
}

/**
 * Resolve argv for ``language`` (absolute bash when needed). Returns ``null`` +
 * stderr when the launcher is missing / is a rejected WSL trampoline — fail-fast,
 * never hang on a broken System32\\bash.exe.
 *
 * python/node keep bare names so Windows PATHEXT / ``.cmd`` shims still work
 * via CreateProcess; only bash is absolutized.
 */
function resolveLangCmd(
  language: string,
  lang: { cmd: string[]; ext: string },
): { cmd: string[] } | { error: string } {
  if (language === "bash") {
    const bash = resolveBashLauncher();
    if (!bash) {
      return { error: launcherMissingStderr("bash", "bash") };
    }
    return { cmd: [bash] };
  }
  const binName = lang.cmd[0];
  if (!whichCommand(binName)) {
    return { error: launcherMissingStderr(binName, language) };
  }
  return { cmd: [...lang.cmd] };
}

/**
 * 在 `cwd` 下跑一个脚本文件，捕获 stdout/stderr，超时则强杀。
 *
 * 镜像服务端 SubprocessSandbox：超时 → stdout 清空、stderr 写超时说明、exit -1；
 * 进程起不来（如 PATH 无 python）→ 失败结果而非抛错，保证通道总收到信封。永不 reject。
 */
function runSubprocess(
  cmd: string[],
  scriptFile: string,
  cwd: string,
  stdin: string | null,
  timeoutSeconds: number,
  startedMs: number,
  envExtra?: Record<string, string>,
): Promise<WorkspaceOpResult> {
  return new Promise((resolve) => {
    const [bin, ...preArgs] = cmd;
    const child = spawn(bin, [...preArgs, scriptFile], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
      env: envExtra ? { ...process.env, ...envExtra } : undefined,
    });
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let settled = false;

    child.stdout.on("data", (chunk: Buffer) => {
      if (stdout.length < EXEC_CAPTURE_CAP) stdout += decodePipeChunk(chunk);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      if (stderr.length < EXEC_CAPTURE_CAP) stderr += decodePipeChunk(chunk);
    });
    // 进程未读 stdin 即退出会让写入抛 EPIPE——吞掉，不让它变成未捕获错误。
    child.stdin.on("error", () => {});

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, timeoutSeconds * 1000);

    const finish = (r: WorkspaceOpResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(r);
    };

    child.on("error", (err) => {
      finish(
        execResult({
          success: false,
          stdout,
          stderr: stderr || `Failed to start process: ${err.message}`,
          exit_code: -1,
          duration_ms: Date.now() - startedMs,
        }),
      );
    });
    child.on("close", (code) => {
      const duration_ms = Date.now() - startedMs;
      if (timedOut) {
        finish(
          execResult({
            success: false,
            stdout: "",
            stderr: `Timeout: execution exceeded ${timeoutSeconds}s`,
            exit_code: -1,
            duration_ms,
          }),
        );
        return;
      }
      finish(
        execResult({
          success: code === 0,
          stdout,
          stderr,
          exit_code: code ?? 0,
          duration_ms,
        }),
      );
    });

    if (stdin != null) child.stdin.write(stdin);
    child.stdin.end();
  });
}

export async function opExecute(
  root: StoredRoot,
  args: Record<string, unknown>,
): Promise<WorkspaceOpResult> {
  const startedMs = Date.now();
  const language = String(args.language ?? "python");
  const lang = EXEC_LANGS[language];
  if (!lang) {
    return execResult({
      success: false,
      stdout: "",
      stderr: `Unsupported language: ${language}`,
      exit_code: 1,
      duration_ms: 0,
    });
  }

  const resolved = resolveLangCmd(language, lang);
  if ("error" in resolved) {
    return execResult({
      success: false,
      stdout: "",
      stderr: resolved.error,
      exit_code: 127,
      duration_ms: Date.now() - startedMs,
    });
  }

  const code = String(args.code ?? "");
  const stdin = args.stdin == null ? null : String(args.stdin);
  // 通道上限 = EXEC_TIMEOUT_CAP_S（须覆盖 test_run 验证预算）；工具层自己的上限
  // （code_execute ≤60）在服务端 clamp，本处只兑现请求方给出的 timeout_seconds。
  const timeoutSeconds = Math.max(
    1,
    Math.min(Number(args.timeout_seconds ?? 30), EXEC_TIMEOUT_CAP_S),
  );

  // cwd = 工作区子路径（工作区对称化 D1a）：把进程工作目录定到该子树，使本地执行与文件工具
  // 同目录（呼应服务端 cwd=workspace）。`""` / `"."` = 绑定根自身（现行为）。子树尚不存在
  // （裸聊懒建后还没产文件就先执行）→ 回退根，避免用不存在的 cwd 拉起进程而失败。
  const cwdRel = String(args.cwd ?? "");
  const sub = cwdRel === "." ? "" : cwdRel.replace(/^\/+|\/+$/g, "");
  let cwdAbs = root.absPath;
  if (sub) {
    const resolvedPath = resolveLexical(root, sub);
    const real = resolvedPath ? await realInside(root, resolvedPath) : null;
    if (real?.ok) cwdAbs = real.path;
  }

  // 脚本写入临时目录（与服务端一致：代码文件在临时区，进程 cwd 才是工作区）。
  let tmpDir: string;
  try {
    tmpDir = await fs.mkdtemp(join(tmpdir(), "agentcore-exec-"));
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  }
  try {
    const scriptFile = join(tmpDir, `main${lang.ext}`);
    await fs.writeFile(scriptFile, code, "utf-8");
    // W3: inject AGENTCORE_EXTERNAL_* + D11′ PYTHONPATH (. + src/lib) so local
    // code_execute can import src-layout packages the same way TestExitCode does.
    const envExtra: Record<string, string> = {
      ...buildExternalEnvFromRoots(
        args.external_roots as Record<string, unknown> | undefined,
        String(args.conversation_id ?? ""),
      ),
    };
    if (language === "python") {
      Object.assign(envExtra, buildWorkspacePythonpathEnv(cwdAbs));
    }
    return await runSubprocess(
      resolved.cmd,
      scriptFile,
      cwdAbs,
      stdin,
      timeoutSeconds,
      startedMs,
      Object.keys(envExtra).length > 0 ? envExtra : undefined,
    );
  } catch (e) {
    return opErr("WorkspaceIOError", toReason(e));
  } finally {
    await fs.rm(tmpDir, { recursive: true, force: true }).catch(() => {});
  }
}
