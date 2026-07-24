import { describe, expect, it } from "vitest";
import {
  type HandoffFileChange,
  buildReviewRows,
  buildSelections,
  classifyThreeWay,
  countChanges,
  defaultDecision,
  sha256HexFromBase64,
} from "../handoff-review";

function change(
  over: Partial<HandoffFileChange> & { path: string },
): HandoffFileChange {
  return {
    path: over.path,
    changeType: over.changeType ?? "modified",
    baseSha: over.baseSha ?? null,
    resultSha: over.resultSha ?? null,
    isBinary: over.isBinary ?? false,
    content: over.content ?? null,
    sizeBytes: over.sizeBytes ?? 0,
  };
}

describe("classifyThreeWay (镜像后端权威判定)", () => {
  it("local 等于 result 即已应用（幂等重复应用）", () => {
    expect(classifyThreeWay("b", "r", "r")).toBe("applied");
  });

  it("local 仍等于 base 即可干净应用", () => {
    expect(classifyThreeWay("b", "r", "b")).toBe("clean");
  });

  it("local 与两侧都不同即冲突", () => {
    expect(classifyThreeWay("b", "r", "x")).toBe("conflict");
  });

  it("新增（无 base）：本地缺失为干净、本地已有同内容为已应用、本地另有内容为冲突", () => {
    expect(classifyThreeWay(null, "r", null)).toBe("clean");
    expect(classifyThreeWay(null, "r", "r")).toBe("applied");
    expect(classifyThreeWay(null, "r", "x")).toBe("conflict");
  });

  it("删除（无 result）：本地已无为已应用、本地仍等 base 为干净、本地另改为冲突", () => {
    expect(classifyThreeWay("b", null, null)).toBe("applied");
    expect(classifyThreeWay("b", null, "b")).toBe("clean");
    expect(classifyThreeWay("b", null, "x")).toBe("conflict");
  });

  it("applied 优先于 clean（base 与 result 恰相等的退化情形）", () => {
    expect(classifyThreeWay("s", "s", "s")).toBe("applied");
  });
});

describe("defaultDecision", () => {
  it("干净 / 已应用默认取云端，冲突默认保留本地", () => {
    expect(defaultDecision("clean")).toBe("cloud");
    expect(defaultDecision("applied")).toBe("cloud");
    expect(defaultDecision("conflict")).toBe("local");
  });
});

describe("buildReviewRows", () => {
  const changes = [
    change({
      path: "add.txt",
      changeType: "added",
      baseSha: null,
      resultSha: "r1",
    }),
    change({ path: "clean.txt", baseSha: "b2", resultSha: "r2" }),
    change({ path: "conflict.txt", baseSha: "b3", resultSha: "r3" }),
    change({ path: "done.txt", baseSha: "b4", resultSha: "r4" }),
  ];
  const shas = new Map<string, string | null>([
    // add.txt absent locally → null
    ["clean.txt", "b2"],
    ["conflict.txt", "x3"],
    ["done.txt", "r4"],
  ]);

  it("逐文件三方判定并赋缺省决策（缺项视为本地不存在）", () => {
    const rows = buildReviewRows(changes, shas);
    expect(rows.map((r) => [r.change.path, r.verdict, r.decision])).toEqual([
      ["add.txt", "clean", "cloud"],
      ["clean.txt", "clean", "cloud"],
      ["conflict.txt", "conflict", "local"],
      ["done.txt", "applied", "cloud"],
    ]);
    expect(rows[0].localSha).toBeNull();
    expect(rows[2].localSha).toBe("x3");
  });
});

describe("buildSelections", () => {
  it("折成选择集；force 仅在冲突行选云端时为真，并带上本地哈希", () => {
    const rows = buildReviewRows(
      [
        change({ path: "clean.txt", baseSha: "b", resultSha: "r" }),
        change({ path: "conflict.txt", baseSha: "b", resultSha: "r" }),
        change({ path: "done.txt", baseSha: "b", resultSha: "r" }),
      ],
      new Map([
        ["clean.txt", "b"],
        ["conflict.txt", "x"],
        ["done.txt", "r"],
      ]),
    );
    // 把冲突行显式改选云端（= 强制覆盖）
    rows[1].decision = "cloud";

    expect(buildSelections(rows)).toEqual([
      { path: "clean.txt", decision: "cloud", localSha: "b", force: false },
      { path: "conflict.txt", decision: "cloud", localSha: "x", force: true },
      { path: "done.txt", decision: "cloud", localSha: "r", force: false },
    ]);
  });

  it("冲突行保留本地时不 force", () => {
    const rows = buildReviewRows(
      [change({ path: "c.txt", baseSha: "b", resultSha: "r" })],
      new Map([["c.txt", "x"]]),
    );
    expect(buildSelections(rows)).toEqual([
      { path: "c.txt", decision: "local", localSha: "x", force: false },
    ]);
  });
});

describe("countChanges", () => {
  it("按种类计数", () => {
    expect(
      countChanges([
        change({ path: "a", changeType: "added" }),
        change({ path: "b", changeType: "added" }),
        change({ path: "c", changeType: "modified" }),
        change({ path: "d", changeType: "deleted" }),
      ]),
    ).toEqual({ added: 2, modified: 1, deleted: 1 });
  });
});

describe("sha256HexFromBase64 (须与服务端 hashlib.sha256(bytes).hexdigest() 一致)", () => {
  it("空内容", async () => {
    expect(await sha256HexFromBase64("")).toBe(
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    );
  });

  it("已知向量 abc（base64 YWJj）", async () => {
    expect(await sha256HexFromBase64("YWJj")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });
});
