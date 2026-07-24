import {
  type AskUserContent,
  composeAnswer,
} from "@/components/chat/ask/AskUserFields";
import type { WorkspaceBinding } from "@/services/workspaceBinding";
import type { FsRoot } from "@shared/ipc-contract";
import { describe, expect, it } from "vitest";
import { formatBindLocalFolderAnswer } from "../bindLocalFolder";
import {
  formatWorkspaceChipLabel,
  resolveEffectiveWorkspace,
} from "../workspaceEffectiveMode";

const roots: FsRoot[] = [
  { id: "root-bound", name: "MyRepo" },
  { id: "root-container", name: "AgentCore" },
];

const cloud: WorkspaceBinding = {
  mode: "cloud",
  scope: "conversation",
  rootId: null,
  source: null,
};

const localBound: WorkspaceBinding = {
  mode: "local",
  scope: "conversation",
  rootId: "root-bound",
  source: "explicit",
};

const projectLocal: WorkspaceBinding = {
  mode: "local",
  scope: "folder",
  rootId: "root-bound",
  source: "explicit",
};

describe("formatBindLocalFolderAnswer", () => {
  it("appends the folder name so the AI knows what was bound", () => {
    expect(formatBindLocalFolderAnswer("绑定本地文件夹", "docs")).toBe(
      "绑定本地文件夹（docs）",
    );
  });
});

describe("composeAnswer with bind_local_folder pick", () => {
  const content: AskUserContent = {
    question: "需要本地目录吗？",
    context: "",
    assumptions: [],
    questions: [
      {
        id: "q0",
        prompt: "工作区",
        kind: "choice",
        options: [
          { label: "绑定本地文件夹", action: "bind_local_folder" },
          { label: "继续用云端" },
        ],
        multiple: false,
        default: "",
      },
    ],
    styleOptions: [],
  };

  it("puts the folder-annotated option into the composed resolve text", () => {
    const text = composeAnswer(
      content,
      {
        q0: [
          formatBindLocalFolderAnswer("绑定本地文件夹", "AgentCore-desktop"),
        ],
      },
      {},
      {},
      null,
      "",
      false,
    );
    expect(text).toContain("绑定本地文件夹（AgentCore-desktop）");
    expect(text).toMatch(/^我的答复：/);
  });
});

describe("resolveEffectiveWorkspace (chip status source)", () => {
  it("treats an explicit bind as local with that root name", () => {
    const ws = resolveEffectiveWorkspace({
      binding: localBound,
      localContainerRootId: "root-container",
      roots,
    });
    expect(ws.isLocal).toBe(true);
    expect(ws.rootId).toBe("root-bound");
    expect(ws.rootName).toBe("MyRepo");
    expect(ws.viaContainer).toBe(false);
    expect(formatWorkspaceChipLabel(ws)).toBe("草稿 · 本地");
  });

  it("labels project inheritance as 项目名 · 本地", () => {
    const ws = resolveEffectiveWorkspace({
      binding: projectLocal,
      localContainerRootId: null,
      roots,
      projectName: "Acme",
    });
    expect(ws.viaProject).toBe(true);
    expect(formatWorkspaceChipLabel(ws)).toBe("Acme · 本地");
  });

  it("treats default container root as local when binding is cloud", () => {
    const ws = resolveEffectiveWorkspace({
      binding: cloud,
      localContainerRootId: "root-container",
      roots,
    });
    expect(ws.isLocal).toBe(true);
    expect(ws.viaContainer).toBe(true);
    expect(formatWorkspaceChipLabel(ws)).toBe("草稿 · 本地");
  });

  it("shows 草稿 · 云 when neither bind nor container is set", () => {
    const ws = resolveEffectiveWorkspace({
      binding: cloud,
      localContainerRootId: null,
      roots,
    });
    expect(ws.isLocal).toBe(false);
    expect(formatWorkspaceChipLabel(ws)).toBe("草稿 · 云");
  });
});
