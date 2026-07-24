import { __resetCapabilitiesCacheForTests } from "@/components/tools/useCapabilities";
import type { Capabilities } from "@/services/capabilities";
// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GuidelinesPage } from "../GuidelinesPage";

vi.mock("@/services/capabilities", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/services/capabilities")>();
  return {
    ...actual,
    getCapabilities: vi.fn(),
  };
});

const { getCapabilities } = await import("@/services/capabilities");

const base: Capabilities = {
  guidelines: {
    shared_base: "共享准则正文",
    ceo_addon: "CEO 附加正文",
    ceo: "完整 CEO 提示词",
  },
  skills: [
    {
      name: "delegate_playbook",
      summary: "派单进阶",
      body: "body",
    },
  ],
  tools: [],
  packs: [],
};

beforeEach(() => {
  __resetCapabilitiesCacheForTests();
  vi.mocked(getCapabilities).mockReset();
});

afterEach(cleanup);

function renderPage() {
  return render(
    <MemoryRouter>
      <GuidelinesPage />
    </MemoryRouter>,
  );
}

describe("GuidelinesPage 能力包向后兼容", () => {
  it("packs 缺失时与现状一致：不渲染能力包区，仍显示准则与薄技能", async () => {
    // Simulate older backends that omit `packs` (OpenAPI marks it optional with default []).
    const { packs: _packs, ...withoutPacks } = base;
    vi.mocked(getCapabilities).mockResolvedValue(withoutPacks as Capabilities);
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("全员共享准则")).toBeTruthy();
    });
    expect(screen.queryByTestId("capability-packs")).toBeNull();
    expect(screen.getByText("工具进阶用法（薄技能）")).toBeTruthy();
    expect(screen.getByText("delegate_playbook")).toBeTruthy();
  });

  it("packs 为空数组时不渲染能力包区", async () => {
    vi.mocked(getCapabilities).mockResolvedValue({ ...base, packs: [] });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("全员共享准则")).toBeTruthy();
    });
    expect(screen.queryByTestId("capability-packs")).toBeNull();
  });

  it("有 packs 时渲染纯展示卡片，并从薄技能区去重包内技能", async () => {
    vi.mocked(getCapabilities).mockResolvedValue({
      ...base,
      skills: [
        ...base.skills,
        {
          name: "contract_review",
          summary: "审查合同",
          body: "body",
        },
      ],
      packs: [
        {
          id: "legal",
          name: "法律能力",
          summary: "合同审查与合规",
          skills: [
            {
              name: "contract_review",
              summary: "审查合同",
              body: "body",
            },
          ],
        },
      ],
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("capability-packs")).toBeTruthy();
    });
    expect(screen.getByText("能力包")).toBeTruthy();
    expect(screen.getByText("法律能力")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /启用|停用/ })).toBeNull();
    // Pack skill shown once under the pack card, not again in thin-skills strip.
    expect(screen.getAllByText("contract_review")).toHaveLength(1);
    expect(screen.getByText("delegate_playbook")).toBeTruthy();
  });
});
