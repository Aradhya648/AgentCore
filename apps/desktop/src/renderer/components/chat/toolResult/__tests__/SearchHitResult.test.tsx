// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type ToolResultData, ToolResultView } from "../ToolResultView";

const { showFile } = vi.hoisted(() => ({
  showFile: vi.fn(),
}));

vi.mock("@/stores/sidePanel", () => ({
  useSidePanelStore: (sel: (s: { showFile: typeof showFile }) => unknown) =>
    sel({ showFile }),
}));

afterEach(cleanup);

beforeEach(() => {
  showFile.mockClear();
});

function data(p: Partial<ToolResultData>): ToolResultData {
  return {
    toolName: "x",
    args: {},
    result: null,
    display: null,
    status: "success",
    ...p,
  };
}

describe("ToolResultView · grep / code_search clickable paths", () => {
  it("grep hit path click calls showFile(path, name)", () => {
    render(
      <ToolResultView
        data={data({
          toolName: "grep",
          result: [
            "1 处匹配，分布在 1 个文件中（/Foo/）",
            "src/widgets/Foo.tsx:42: export function Foo()",
          ].join("\n"),
        })}
      />,
    );
    const link = screen.getByRole("button", {
      name: "src/widgets/Foo.tsx:42",
    });
    fireEvent.click(link);
    expect(showFile).toHaveBeenCalledWith(
      "src/widgets/Foo.tsx",
      "Foo.tsx",
    );
  });

  it("code_search hit path click calls showFile", () => {
    render(
      <ToolResultView
        data={data({
          toolName: "code_search",
          result: [
            "lib/util.py:12-40  helper (function) (python)",
            "  def helper():",
            "  score=0.91",
          ].join("\n"),
        })}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "lib/util.py:12-40" }),
    );
    expect(showFile).toHaveBeenCalledWith("lib/util.py", "util.py");
  });

  it("empty「可执行下一步」stays plain text (no path buttons)", () => {
    render(
      <ToolResultView
        data={data({
          toolName: "grep",
          result:
            "本次 grep 未匹配 /x/。不要据此断定代码不存在。可执行下一步：① 收窄或放宽 path/glob；",
        })}
      />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/可执行下一步/)).toBeTruthy();
  });
});
