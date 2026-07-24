import { describe, expect, it } from "vitest";
import { lineDiff } from "../diff";

describe("lineDiff", () => {
  it("marks a changed line as del+add and keeps surrounding context", () => {
    expect(lineDiff("a\nb\nc", "a\nB\nc")).toEqual([
      { type: "context", text: "a" },
      { type: "del", text: "b" },
      { type: "add", text: "B" },
      { type: "context", text: "c" },
    ]);
  });

  it("handles a pure insertion", () => {
    expect(lineDiff("a\nc", "a\nb\nc")).toEqual([
      { type: "context", text: "a" },
      { type: "add", text: "b" },
      { type: "context", text: "c" },
    ]);
  });

  it("handles a pure deletion", () => {
    expect(lineDiff("a\nb\nc", "a\nc")).toEqual([
      { type: "context", text: "a" },
      { type: "del", text: "b" },
      { type: "context", text: "c" },
    ]);
  });

  it("treats identical text as all context", () => {
    expect(lineDiff("x\ny", "x\ny")).toEqual([
      { type: "context", text: "x" },
      { type: "context", text: "y" },
    ]);
  });

  it("dels all old then adds all new on a full rewrite", () => {
    expect(lineDiff("a\nb", "c\nd")).toEqual([
      { type: "del", text: "a" },
      { type: "del", text: "b" },
      { type: "add", text: "c" },
      { type: "add", text: "d" },
    ]);
  });
});
