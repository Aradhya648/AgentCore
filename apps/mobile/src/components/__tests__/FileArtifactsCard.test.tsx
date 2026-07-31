// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { FileArtifactsCard } from "../FileArtifactsCard";

describe("FileArtifactsCard acceptance labels", () => {
  it("shows 已验收/未通过 and never 写入/编辑 on acceptance rows", () => {
    render(
      <MemoryRouter>
        <FileArtifactsCard
          conversationId="c1"
          artifacts={[
            {
              path: "ok.md",
              name: "ok.md",
              acceptance: "accepted",
            },
            {
              path: "bad.md",
              name: "bad.md",
              acceptance: "rejected",
              acceptanceReason: "citations_unverified",
              acceptanceDetail: "缺引用",
            },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("已验收")).toBeTruthy();
    expect(screen.getByText("未通过")).toBeTruthy();
    expect(screen.queryByText("写入")).toBeNull();
    expect(screen.queryByText("编辑")).toBeNull();
  });

  it("write/edit tool rows omit op badges", () => {
    render(
      <MemoryRouter>
        <FileArtifactsCard
          conversationId="c1"
          artifacts={[
            { path: "src/main.ts", name: "main.ts", op: "write" },
            { path: "src/a.ts", name: "a.ts", op: "edit" },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByText("写入")).toBeNull();
    expect(screen.queryByText("编辑")).toBeNull();
  });
});

describe("FileArtifactsCard stage labels", () => {
  it("AgentCore/文档/research/debate 路径显示案卷标签，普通路径零噪音", () => {
    render(
      <MemoryRouter>
        <FileArtifactsCard
          conversationId="c1"
          artifacts={[
            {
              path: "AgentCore/文档/research/brief.md",
              name: "brief.md",
              op: "write",
            },
            {
              path: "AgentCore/文档/debate/round.md",
              name: "round.md",
              op: "write",
            },
            { path: "notes.txt", name: "notes.txt", op: "write" },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("调研案卷")).toBeTruthy();
    expect(screen.getByText("辩论产物")).toBeTruthy();
    expect(
      screen.getByTitle("在文件页查看案卷 AgentCore/文档/research/brief.md"),
    ).toBeTruthy();
    expect(screen.getByTitle("在工作区查看 notes.txt")).toBeTruthy();
  });
});
