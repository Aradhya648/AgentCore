import type { FileSource } from "@/lib/fileSource";
import { asReadOnlyFileSource } from "@/services/sources/readOnlyFileSource";
import { describe, expect, it, vi } from "vitest";

function stubSource(): FileSource {
  return {
    id: "local:root",
    label: "demo",
    caps: { watch: true, transfer: false, edit: true, snapshots: false },
    listDir: vi.fn(async () => []),
    read: vi.fn(async () => ({
      kind: "text" as const,
      text: "hi",
      truncated: false,
    })),
    createFile: vi.fn(async () => {}),
    mkdir: vi.fn(async () => {}),
    move: vi.fn(async () => {}),
    delete: vi.fn(async () => {}),
    writeText: vi.fn(async () => ({
      ok: true as const,
      version: { mtimeMs: 1 },
    })),
  };
}

describe("asReadOnlyFileSource (N4-A)", () => {
  it("clears edit/transfer caps and rejects writes", async () => {
    const ro = asReadOnlyFileSource(stubSource());
    expect(ro.caps.edit).toBe(false);
    expect(ro.caps.transfer).toBe(false);
    expect(ro.caps.watch).toBe(true);
    await expect(ro.createFile("a.txt")).rejects.toThrow(/离线只读/);
    const writeText = ro.writeText;
    expect(writeText).toBeDefined();
    if (!writeText) return;
    const write = await writeText("a.txt", {
      content: "x",
      encoding: "utf-8",
      eol: "lf",
      baseline: null,
    });
    expect(write.ok).toBe(false);
    if (!write.ok) expect(write.reason).toBe("denied");
  });

  it("still lists and reads", async () => {
    const base = stubSource();
    const ro = asReadOnlyFileSource(base);
    await ro.listDir("");
    await ro.read("a.txt");
    expect(base.listDir).toHaveBeenCalled();
    expect(base.read).toHaveBeenCalled();
  });
});
