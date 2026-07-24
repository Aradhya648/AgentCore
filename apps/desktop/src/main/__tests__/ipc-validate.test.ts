import { describe, expect, it } from "vitest";
import {
  IpcInvalidArgsError,
  assertShape,
  isRecord,
  requireStringFields,
} from "../ipc-validate";

describe("ipc-validate（IPC 边界结构校验 · IPC-004）", () => {
  describe("isRecord", () => {
    it("接受对象、拒绝原始值与 null", () => {
      expect(isRecord({})).toBe(true);
      expect(isRecord({ a: 1 })).toBe(true);
      expect(isRecord(null)).toBe(false);
      expect(isRecord(undefined)).toBe(false);
      expect(isRecord("x")).toBe(false);
      expect(isRecord(42)).toBe(false);
    });
  });

  describe("requireStringFields", () => {
    it("全部键为 string 时返回窄化对象", () => {
      expect(
        requireStringFields({ rootId: "r", relPath: "a/b" }, [
          "rootId",
          "relPath",
        ]),
      ).toEqual({ rootId: "r", relPath: "a/b" });
    });

    it("任一键缺失 / 非 string / 非对象时返回 null", () => {
      expect(
        requireStringFields({ rootId: "r" }, ["rootId", "relPath"]),
      ).toBeNull();
      expect(
        requireStringFields({ rootId: 1, relPath: "x" }, ["rootId", "relPath"]),
      ).toBeNull();
      expect(requireStringFields(null, ["rootId"])).toBeNull();
      expect(requireStringFields("nope", ["rootId"])).toBeNull();
      // 数组虽是对象，但不含命名键 → 失败（防止以数组冒充 payload）。
      expect(requireStringFields([], ["rootId"])).toBeNull();
    });

    it("只取列出的键、忽略多余字段", () => {
      expect(
        requireStringFields({ rootId: "r", extra: 9 }, ["rootId"]),
      ).toEqual({
        rootId: "r",
      });
    });
  });

  describe("assertShape", () => {
    it("形状合法时静默通过", () => {
      expect(() =>
        assertShape("c", { rootId: "r", turnId: "t" }, ["rootId", "turnId"]),
      ).not.toThrow();
    });

    it("可选 string 缺省放行、存在且为 string 放行", () => {
      expect(() =>
        assertShape("c", { rootId: "r" }, ["rootId"], ["subpath"]),
      ).not.toThrow();
      expect(() =>
        assertShape(
          "c",
          { rootId: "r", subpath: "sub" },
          ["rootId"],
          ["subpath"],
        ),
      ).not.toThrow();
    });

    it("可选 string 存在但非 string 时抛 IpcInvalidArgsError", () => {
      expect(() =>
        assertShape("c", { rootId: "r", subpath: 5 }, ["rootId"], ["subpath"]),
      ).toThrow(IpcInvalidArgsError);
    });

    it("必需键缺失 / 非对象时抛 IpcInvalidArgsError", () => {
      expect(() =>
        assertShape("c", { rootId: "r" }, ["rootId", "turnId"]),
      ).toThrow(IpcInvalidArgsError);
      expect(() => assertShape("c", null, ["rootId"])).toThrow(
        IpcInvalidArgsError,
      );
    });

    it("错误信息含通道名，便于排查", () => {
      expect(() => assertShape("sidecar:startTurn", {}, ["rootId"])).toThrow(
        /sidecar:startTurn/,
      );
    });
  });
});
