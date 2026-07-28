// @vitest-environment jsdom
import {
  isEditableKeyboardTarget,
  shouldRunGlobalShortcut,
} from "@/lib/shortcuts";
import { describe, expect, it } from "vitest";

describe("isEditableKeyboardTarget", () => {
  it("detects text input / textarea / contenteditable", () => {
    const input = document.createElement("input");
    input.type = "text";
    expect(isEditableKeyboardTarget(input)).toBe(true);

    const area = document.createElement("textarea");
    expect(isEditableKeyboardTarget(area)).toBe(true);

    const editable = document.createElement("div");
    editable.contentEditable = "true";
    expect(isEditableKeyboardTarget(editable)).toBe(true);
  });

  it("ignores non-text inputs and plain elements", () => {
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    expect(isEditableKeyboardTarget(checkbox)).toBe(false);

    const button = document.createElement("button");
    expect(isEditableKeyboardTarget(button)).toBe(false);

    expect(isEditableKeyboardTarget(null)).toBe(false);
  });
});

describe("shouldRunGlobalShortcut", () => {
  it("always allows command palette even in an editable", () => {
    const input = document.createElement("input");
    expect(shouldRunGlobalShortcut("command-palette", input)).toBe(true);
  });

  it("blocks navigation / sidebar chords while editing", () => {
    const input = document.createElement("input");
    expect(shouldRunGlobalShortcut("new-conversation", input)).toBe(false);
    expect(shouldRunGlobalShortcut("toggle-sidebar", input)).toBe(false);
    expect(shouldRunGlobalShortcut("open-workspace-terminal", input)).toBe(
      false,
    );
  });

  it("allows non-palette chords outside editables", () => {
    const div = document.createElement("div");
    expect(shouldRunGlobalShortcut("new-conversation", div)).toBe(true);
  });
});
