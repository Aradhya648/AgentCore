import { describe, expect, it } from "vitest";
import { coerceIpcBytes } from "../fs/ipcBytes";

describe("coerceIpcBytes（fs:saveFile IPC 字节归一）", () => {
  it("接受 Uint8Array", () => {
    const src = new Uint8Array([1, 2, 3]);
    expect(coerceIpcBytes(src)).toEqual(src);
  });

  it("接受 ArrayBuffer（结构化克隆常见形态）", () => {
    const buf = new Uint8Array([9, 8, 7]).buffer;
    expect(coerceIpcBytes(buf)).toEqual(new Uint8Array([9, 8, 7]));
  });

  it("接受其它 TypedArray view（含 byteOffset）", () => {
    const backing = new Uint8Array([0, 0, 4, 5, 6, 0]);
    const view = new Uint8Array(backing.buffer, 2, 3);
    expect(coerceIpcBytes(view)).toEqual(new Uint8Array([4, 5, 6]));
  });

  it("拒绝非二进制", () => {
    expect(coerceIpcBytes(null)).toBeNull();
    expect(coerceIpcBytes(undefined)).toBeNull();
    expect(coerceIpcBytes([1, 2])).toBeNull();
    expect(coerceIpcBytes("abc")).toBeNull();
  });
});
