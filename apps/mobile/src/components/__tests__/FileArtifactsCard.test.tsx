// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { FileArtifactsCard } from "../FileArtifactsCard";

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
