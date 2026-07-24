// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { BlockRenderer } from "../BlockRenderer";
import type { ManualBlock } from "../types";

afterEach(cleanup);

function renderBlock(block: ManualBlock) {
  return render(
    <MemoryRouter>
      <BlockRenderer block={block} />
    </MemoryRouter>,
  );
}

describe("BlockRenderer", () => {
  it("renders lead", () => {
    renderBlock({ type: "lead", text: "导语段落" });
    expect(screen.getByText("导语段落")).toBeTruthy();
  });

  it("renders emphasized paragraph", () => {
    renderBlock({ type: "paragraph", text: "小标题", emphasis: true });
    expect(screen.getByText("小标题")).toBeTruthy();
  });

  it("renders tip and info callouts with distinct styles", () => {
    const { container: tipRoot } = renderBlock({
      type: "callout",
      variant: "tip",
      text: "提示内容",
    });
    const tipClass = tipRoot.firstElementChild?.className ?? "";
    cleanup();
    const { container: infoRoot } = renderBlock({
      type: "callout",
      variant: "info",
      text: "说明内容",
    });
    const infoClass = infoRoot.firstElementChild?.className ?? "";
    expect(tipClass).toContain("bg-primary/5");
    expect(infoClass).toContain("bg-muted/30");
    expect(tipClass).not.toBe(infoClass);
    expect(screen.getByText("说明内容")).toBeTruthy();
  });

  it("renders cards grid", () => {
    renderBlock({
      type: "cards",
      cols: 3,
      items: [
        { title: "卡 A", desc: "描述 A" },
        { title: "卡 B", desc: "描述 B", highlight: true, icon: "Crown" },
      ],
    });
    expect(screen.getByText("卡 A")).toBeTruthy();
    expect(screen.getByText("卡 B")).toBeTruthy();
    expect(screen.getByText("描述 B")).toBeTruthy();
  });

  it("renders bullets", () => {
    renderBlock({
      type: "bullets",
      items: [{ title: "要点", desc: "说明" }],
    });
    expect(screen.getByText("要点")).toBeTruthy();
  });

  it("renders steps with go-link rich text", () => {
    renderBlock({
      type: "steps",
      items: [
        {
          title: "填 Key",
          desc: [
            "去 ",
            {
              text: "设置 · 模型配置",
              link: { kind: "go", to: "/more/model" },
            },
          ],
        },
      ],
    });
    expect(screen.getByText("填 Key")).toBeTruthy();
    expect(screen.getByText("设置 · 模型配置")).toBeTruthy();
  });

  it("renders doDont", () => {
    renderBlock({
      type: "doDont",
      good: { items: ["好说法"] },
      bad: { items: ["差说法"] },
    });
    expect(screen.getByText("好说法")).toBeTruthy();
    expect(screen.getByText("差说法")).toBeTruthy();
  });

  it("renders faq with nested boundary table", () => {
    renderBlock({
      type: "faq",
      items: [
        {
          q: "边界？",
          a: [
            { type: "text", text: "三类边界：" },
            {
              type: "boundaryTable",
              rows: [
                {
                  can: "读文件",
                  approve: "改文件",
                  wont: "force push",
                },
              ],
            },
          ],
        },
      ],
    });
    expect(screen.getByText("边界？")).toBeTruthy();
    expect(screen.getByText("会做")).toBeTruthy();
    expect(screen.getByText("读文件")).toBeTruthy();
    expect(screen.getByText("force push")).toBeTruthy();
  });

  it("renders boundaryTable block", () => {
    renderBlock({
      type: "boundaryTable",
      rows: [{ can: "A", approve: "B", wont: "C" }],
    });
    expect(screen.getByText("A")).toBeTruthy();
    expect(screen.getByText("B")).toBeTruthy();
    expect(screen.getByText("C")).toBeTruthy();
  });

  it("renders settingsRows", () => {
    renderBlock({
      type: "settingsRows",
      rows: [{ label: "模型配置", desc: "填 Key", to: "/more/model" }],
    });
    expect(screen.getByText("模型配置")).toBeTruthy();
    expect(screen.getByText("填 Key")).toBeTruthy();
  });

  it("renders unknown embed as fallback message", () => {
    renderBlock({ type: "embed", key: "DoesNotExist" });
    expect(screen.getByText(/未注册的嵌入组件/)).toBeTruthy();
  });

  it("renders warning callout", () => {
    renderBlock({
      type: "callout",
      variant: "warning",
      text: "警告文案",
    });
    expect(screen.getByText("警告文案")).toBeTruthy();
  });
});
