import {
  mkdtemp,
  readFile,
  realpath,
  rm,
  stat,
  symlink,
  utimes,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import JSZip from "jszip";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// fs-service imports electron at module load (for IPC wiring it doesn't run
// here). Stub it so the dependency-free executeWorkspaceOp can be imported.
vi.mock("electron", () => ({
  app: { getPath: () => tmpdir() },
  dialog: {},
  ipcMain: { handle: vi.fn() },
  BrowserWindow: { getFocusedWindow: () => null, getAllWindows: () => [] },
  shell: {
    trashItem: async (p: string) => {
      await rm(p, { recursive: true, force: true });
    },
  },
}));

import type { WorkspaceOpResult } from "@shared/ipc-contract";
import { type StoredRoot, executeWorkspaceOp } from "../fs-service";

// Discriminated-union accessors that fail loudly on the wrong branch.
const valOf = (r: WorkspaceOpResult): unknown => {
  if (!r.ok) throw new Error(`expected ok, got ${JSON.stringify(r.error)}`);
  return r.value;
};
const errOf = (r: WorkspaceOpResult) => {
  if (r.ok)
    throw new Error(`expected error, got value ${JSON.stringify(r.value)}`);
  return r.error;
};

describe("executeWorkspaceOp (本地工作区写类 op，P2b)", () => {
  let dir: string;
  let root: StoredRoot;
  // realpath the temp dir: os.tmpdir() is often a symlink (macOS /tmp), and the
  // traversal guard compares against the canonical root.
  beforeEach(async () => {
    dir = await realpath(await mkdtemp(join(tmpdir(), "ws-")));
    root = { id: "r", name: "r", absPath: dir };
  });
  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  const run = (op: string, args: Record<string, unknown>) =>
    executeWorkspaceOp(root, op as never, args);

  it("write creates the file with parents and reports the code-point count", async () => {
    // "hi😀" = 3 code points (the emoji is one), matching Python len() — not the
    // 4 UTF-16 units JS .length would give.
    const r = await run("write", { path: "a/b/c.txt", content: "hi😀" });
    expect(valOf(r)).toBe(3);
    expect(await readFile(join(dir, "a/b/c.txt"), "utf-8")).toBe("hi😀");
  });

  it("write overwrites an existing file atomically", async () => {
    await run("write", { path: "f.txt", content: "old" });
    const r = await run("write", { path: "f.txt", content: "fresh" });
    expect(r.ok).toBe(true);
    expect(await readFile(join(dir, "f.txt"), "utf-8")).toBe("fresh");
  });

  it("append creates a file or extends an existing one", async () => {
    const created = await run("append", { path: "d.md", content: "# A" });
    expect(valOf(created)).toBe(3);
    expect(await readFile(join(dir, "d.md"), "utf-8")).toBe("# A");
    const extended = await run("append", { path: "d.md", content: "\n\n# B" });
    expect(valOf(extended)).toBe(5);
    expect(await readFile(join(dir, "d.md"), "utf-8")).toBe("# A\n\n# B");
  });

  it("read_bytes round-trips raw bytes as base64 and reports PathNotFound", async () => {
    const raw = Buffer.from([0, 1, 2, 255]);
    await writeFile(join(dir, "blob"), raw);
    const r = await run("read_bytes", { path: "blob" });
    expect(Buffer.from(valOf(r) as string, "base64")).toEqual(raw);
    expect(errOf(await run("read_bytes", { path: "nope" })).kind).toBe(
      "PathNotFound",
    );
  });

  it("write_bytes decodes base64 and reports the byte count", async () => {
    const raw = Buffer.from([10, 20, 30, 40]);
    const r = await run("write_bytes", {
      path: "out.bin",
      data: raw.toString("base64"),
    });
    expect(valOf(r)).toBe(4);
    expect(await readFile(join(dir, "out.bin"))).toEqual(raw);
  });

  it("mkdir creates nested dirs and refuses an existing path", async () => {
    expect((await run("mkdir", { path: "x/y/z" })).ok).toBe(true);
    expect((await stat(join(dir, "x/y/z"))).isDirectory()).toBe(true);
    expect(errOf(await run("mkdir", { path: "x/y/z" })).kind).toBe(
      "AlreadyExists",
    );
  });

  it("delete removes a file and a directory tree, else PathNotFound", async () => {
    await run("write", { path: "d/f.txt", content: "x" });
    expect((await run("delete", { path: "d/f.txt" })).ok).toBe(true);
    expect((await run("delete", { path: "d" })).ok).toBe(true);
    expect(errOf(await run("delete", { path: "ghost" })).kind).toBe(
      "PathNotFound",
    );
  });

  it("copy duplicates a file and a directory tree without clobber", async () => {
    await run("write", { path: "src.txt", content: "data" });
    expect(
      (await run("copy", { src: "src.txt", dst: "nested/dst.txt" })).ok,
    ).toBe(true);
    expect(await readFile(join(dir, "src.txt"), "utf-8")).toBe("data");
    expect(await readFile(join(dir, "nested/dst.txt"), "utf-8")).toBe("data");
    expect(
      errOf(await run("copy", { src: "src.txt", dst: "nested/dst.txt" })).kind,
    ).toBe("AlreadyExists");

    await run("mkdir", { path: "tree/a" });
    await run("write", { path: "tree/a/b.txt", content: "b" });
    expect((await run("copy", { src: "tree", dst: "tree2" })).ok).toBe(true);
    expect(await readFile(join(dir, "tree2/a/b.txt"), "utf-8")).toBe("b");
  });

  it("permanent delete hard-removes; default delete leaves workspace via trash", async () => {
    await run("write", { path: "hard.txt", content: "x" });
    expect(
      (await run("delete", { path: "hard.txt", permanent: true })).ok,
    ).toBe(true);
    expect(errOf(await run("read", { path: "hard.txt" })).kind).toBe(
      "PathNotFound",
    );
  });

  it("move renames, creates dst parents, and guards clobber / missing src", async () => {
    await run("write", { path: "src.txt", content: "data" });
    expect(
      (await run("move", { src: "src.txt", dst: "nested/dst.txt" })).ok,
    ).toBe(true);
    expect(await readFile(join(dir, "nested/dst.txt"), "utf-8")).toBe("data");
    expect(errOf(await run("read", { path: "src.txt" })).kind).toBe(
      "PathNotFound",
    );

    await run("write", { path: "taken.txt", content: "1" });
    expect(
      errOf(await run("move", { src: "nested/dst.txt", dst: "taken.txt" }))
        .kind,
    ).toBe("AlreadyExists");
    expect(errOf(await run("move", { src: "ghost", dst: "z.txt" })).kind).toBe(
      "PathNotFound",
    );
  });

  it("replace (single) returns count 1 and the 1-based first line", async () => {
    await run("write", { path: "r.txt", content: "a\nbXb\nc" });
    const r = await run("replace", {
      path: "r.txt",
      old: "X",
      new: "Y",
      all: false,
    });
    expect(valOf(r)).toEqual({ count: 1, first_line: 2 });
    expect(await readFile(join(dir, "r.txt"), "utf-8")).toBe("a\nbYb\nc");
  });

  it("replace (all) returns the total count and a null first line", async () => {
    await run("write", { path: "r.txt", content: "x x x" });
    const r = await run("replace", {
      path: "r.txt",
      old: "x",
      new: "y",
      all: true,
    });
    expect(valOf(r)).toEqual({ count: 3, first_line: null });
    expect(await readFile(join(dir, "r.txt"), "utf-8")).toBe("y y y");
  });

  it("replace surfaces AmbiguousMatch with the match count when not all", async () => {
    await run("write", { path: "r.txt", content: "x x" });
    const err = errOf(
      await run("replace", { path: "r.txt", old: "x", new: "y", all: false }),
    );
    expect(err).toEqual({
      kind: "AmbiguousMatch",
      detail: "2 matches",
      count: 2,
    });
  });

  it("replace maps NoMatch / NotUTF8 / NotAFile", async () => {
    await run("write", { path: "r.txt", content: "abc" });
    expect(
      errOf(
        await run("replace", {
          path: "r.txt",
          old: "zzz",
          new: "y",
          all: false,
        }),
      ).kind,
    ).toBe("NoMatch");

    await writeFile(join(dir, "bin"), Buffer.from([0xff, 0xfe, 0x00]));
    expect(
      errOf(
        await run("replace", { path: "bin", old: "x", new: "y", all: false }),
      ).kind,
    ).toBe("NotUTF8");

    await run("mkdir", { path: "adir" });
    expect(
      errOf(
        await run("replace", { path: "adir", old: "x", new: "y", all: false }),
      ).kind,
    ).toBe("NotAFile");
  });

  it("refuses traversal escapes without touching disk", async () => {
    expect(errOf(await run("read", { path: "../escape" })).kind).toBe(
      "OutsideWorkspace",
    );
    expect(
      errOf(await run("write", { path: "../evil.txt", content: "x" })).kind,
    ).toBe("OutsideWorkspace");
  });

  it("rejects a write that escapes through a symlinked ancestor", async () => {
    const outside = await realpath(await mkdtemp(join(tmpdir(), "ws-out-")));
    let linked = true;
    try {
      // "junction" needs no elevation on Windows; ignored (plain symlink) on POSIX.
      await symlink(outside, join(dir, "link"), "junction");
    } catch {
      linked = false; // environment forbids link creation — skip the assertion
    }
    if (linked) {
      expect(
        errOf(await run("write", { path: "link/evil.txt", content: "x" })).kind,
      ).toBe("OutsideWorkspace");
      await expect(
        readFile(join(outside, "evil.txt"), "utf-8"),
      ).rejects.toThrow();
    }
    await rm(outside, { recursive: true, force: true });
  });

  it("routes read / list through the dispatcher", async () => {
    await run("write", { path: "hello.txt", content: "hi" });
    expect(valOf(await run("read", { path: "hello.txt" }))).toBe("hi");
    const entries = valOf(
      await run("list", { directory: ".", pattern: "*" }),
    ) as {
      path: string;
    }[];
    expect(entries.some((e) => e.path === "hello.txt")).toBe(true);
  });

  it("index_files returns a flat, ignore-pruned, posix-sorted file list", async () => {
    await run("write", { path: "a.txt", content: "A" });
    await run("write", { path: "sub/b.md", content: "B" });
    await run("write", { path: "node_modules/dep/index.js", content: "X" }); // pruned
    const res = valOf(await run("index_files", {})) as {
      paths: string[];
      truncated: boolean;
    };
    expect(res.paths).toEqual(["a.txt", "sub/b.md"]); // node_modules pruned, posix sep
    expect(res.truncated).toBe(false);
  });

  it("index_files on an empty root returns no paths", async () => {
    const res = valOf(await run("index_files", {})) as {
      paths: string[];
      truncated: boolean;
    };
    expect(res.paths).toEqual([]);
    expect(res.truncated).toBe(false);
  });

  it("index_files order=recent returns newest-first by mtime", async () => {
    await run("write", { path: "a_old.txt", content: "A" });
    await run("write", { path: "c_mid.txt", content: "C" });
    await run("write", { path: "b_new.txt", content: "B" });
    // Stamp distinct mtimes (seconds): a_old < c_mid < b_new.
    await utimes(join(dir, "a_old.txt"), 100, 100);
    await utimes(join(dir, "c_mid.txt"), 200, 200);
    await utimes(join(dir, "b_new.txt"), 300, 300);
    const recent = valOf(await run("index_files", { order: "recent" })) as {
      paths: string[];
    };
    expect(recent.paths).toEqual(["b_new.txt", "c_mid.txt", "a_old.txt"]);
    // Default order stays alphabetical (the @-mention view), unaffected by mtime.
    const alpha = valOf(await run("index_files", {})) as { paths: string[] };
    expect(alpha.paths).toEqual(["a_old.txt", "b_new.txt", "c_mid.txt"]);
  });

  it("answers a genuinely unknown op as a typed IO error", async () => {
    const err = errOf(await run("bogus_op", {}));
    expect(err.kind).toBe("WorkspaceIOError");
  });

  // Execution tests drive `node` (guaranteed on PATH under vitest, cross-platform)
  // rather than python/bash, which may be absent on the runner.
  describe("execute (P2c, 本地代码执行)", () => {
    const exec = async (args: Record<string, unknown>) =>
      valOf(await run("execute", { language: "javascript", ...args })) as {
        success: boolean;
        stdout: string;
        stderr: string;
        exit_code: number;
        duration_ms: number;
      };

    it("runs code and captures stdout with a zero exit", async () => {
      const r = await exec({ code: "console.log('hi from node')" });
      expect(r.success).toBe(true);
      expect(r.exit_code).toBe(0);
      expect(r.stdout).toContain("hi from node");
    });

    it("runs in the bound root as its working directory", async () => {
      await run("write", { path: "marker.txt", content: "X" });
      const r = await exec({
        code: "console.log(require('node:fs').readdirSync('.').join(','))",
      });
      expect(r.success).toBe(true);
      expect(r.stdout).toContain("marker.txt");
    });

    it("feeds stdin to the process", async () => {
      const r = await exec({
        code: "let b='';process.stdin.on('data',d=>b+=d);process.stdin.on('end',()=>process.stdout.write('got:'+b))",
        stdin: "ping",
      });
      expect(r.stdout).toContain("got:ping");
    });

    it("reports a non-zero exit code as failure", async () => {
      const r = await exec({ code: "process.exit(3)" });
      expect(r.success).toBe(false);
      expect(r.exit_code).toBe(3);
    });

    it("kills a run that exceeds the timeout", async () => {
      const r = await exec({ code: "while (true) {}", timeout_seconds: 1 });
      expect(r.success).toBe(false);
      expect(r.exit_code).toBe(-1);
      expect(r.stderr).toContain("Timeout");
    });

    it("rejects an unsupported language", async () => {
      const r = valOf(
        await run("execute", { language: "ruby", code: "puts 1" }),
      ) as { success: boolean; stderr: string; exit_code: number };
      expect(r.success).toBe(false);
      expect(r.stderr).toContain("Unsupported language");
      expect(r.exit_code).toBe(1);
    });
  });

  // 本地→云交接打包（双模式工作区 P2e / e1）：把整棵绑定根打成单个 zip 交服务端暂存。
  describe("archive (本地→云交接打包, P2e/e1)", () => {
    const archiveNames = async (b64: string): Promise<string[]> => {
      const zip = await JSZip.loadAsync(b64, { base64: true });
      return Object.keys(zip.files)
        .filter((n) => !zip.files[n].dir)
        .sort();
    };

    it("packs the tree, honoring default skips + .gitignore", async () => {
      await run("write", { path: "a.txt", content: "A" });
      await run("write", { path: "sub/b.txt", content: "B" });
      await run("write", { path: "keep.txt", content: "K" });
      await run("write", { path: ".gitignore", content: "secret.txt\n" });
      await run("write", { path: "secret.txt", content: "S" }); // gitignored
      await run("write", { path: "node_modules/junk.js", content: "J" }); // default skip

      const res = valOf(await run("archive", {})) as {
        archive: string;
        file_count: number;
        total_bytes: number;
        truncated: boolean;
      };
      expect(await archiveNames(res.archive)).toEqual([
        ".gitignore",
        "a.txt",
        "keep.txt",
        "sub/b.txt",
      ]);
      const zip = await JSZip.loadAsync(res.archive, { base64: true });
      expect(await zip.file("sub/b.txt")?.async("string")).toBe("B");
      expect(res.file_count).toBe(4);
      expect(res.truncated).toBe(false);
    });

    it("packs only a workspace subdirectory when directory is set", async () => {
      await run("write", { path: "outside.txt", content: "OUT" });
      await run("write", { path: "ws/a.txt", content: "A" });
      await run("write", { path: "ws/nested/b.txt", content: "B" });
      const res = valOf(await run("archive", { directory: "ws" })) as {
        archive: string;
        file_count: number;
      };
      expect(await archiveNames(res.archive)).toEqual([
        "a.txt",
        "nested/b.txt",
      ]);
      expect(res.file_count).toBe(2);
      const zip = await JSZip.loadAsync(res.archive, { base64: true });
      expect(await zip.file("a.txt")?.async("string")).toBe("A");
    });

    it("with ignore:false packs everything (node_modules + gitignored)", async () => {
      await run("write", { path: ".gitignore", content: "secret.txt\n" });
      await run("write", { path: "secret.txt", content: "S" });
      await run("write", { path: "node_modules/junk.js", content: "J" });
      const res = valOf(await run("archive", { ignore: false })) as {
        archive: string;
      };
      const names = await archiveNames(res.archive);
      expect(names).toContain("node_modules/junk.js");
      expect(names).toContain("secret.txt");
    });
  });
});
