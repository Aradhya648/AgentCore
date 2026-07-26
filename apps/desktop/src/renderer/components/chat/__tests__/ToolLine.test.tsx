// @vitest-environment jsdom
/**
 * Render test for ToolLine 过程工具默认折叠: every process tool (web_search / code_execute /
 * file_write / str_replace / …) stays collapsed on the running→done edge — aligned with
 * Cursor/Claude「过程收敛、答案突出」. Folded rows keep inlineCount / peek; expand is a click
 * away. Failures also stay collapsed (red ✗ + red peek). The block comment detaches the
 * @vitest-environment directive from the import block so organizeImports keeps it file-leading.
 */

import { TooltipProvider } from "@/components/ui/tooltip";
import type { ProcessStep } from "@/types/events";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const showBrowser = vi.fn();
vi.mock("@/stores/sidePanel", () => ({
  useSidePanelStore: Object.assign(
    (selector: (s: { showBrowser: typeof showBrowser }) => unknown) =>
      selector({ showBrowser }),
    { getState: () => ({ showBrowser }) },
  ),
}));

import { ToolLine, ToolLineGroup } from "../ToolLine";
import { toolDetail, toolGroupSummary } from "../message-bubble/constants";

afterEach(cleanup);

beforeEach(() => {
  showBrowser.mockReset();
});

function renderWithTooltip(ui: ReactElement) {
  return render(<TooltipProvider>{ui}</TooltipProvider>);
}

type ToolStep = Extract<ProcessStep, { kind: "tool" }>;

function step(over: Partial<ToolStep>): ToolStep {
  return {
    kind: "tool",
    id: "call_1",
    tool_name: "code_execute",
    arguments: {},
    result: null,
    display: null,
    status: "success",
    ...over,
  };
}

function readUrlStep(
  id: string,
  over: {
    url: string;
    title: string;
    site: string;
    snippet?: string;
    content?: string;
    status?: ToolStep["status"];
  },
): ToolStep {
  return step({
    id,
    tool_name: "read_url",
    arguments: { url: over.url },
    result: "ok",
    display: {
      url: over.url,
      title: over.title,
      site: over.site,
      snippet: over.snippet,
      content: over.content ?? "正文不应出现在合并态",
    },
    status: over.status ?? "success",
  });
}

describe("ToolLine · 过程工具默认折叠", () => {
  it("keeps code_execute's terminal collapsed on the running→done edge", () => {
    const { rerender } = render(
      <ToolLine
        step={step({
          tool_name: "code_execute",
          arguments: { code: "print('hi')", language: "python" },
          status: "running",
        })}
      />,
    );
    // Running: nothing to expand yet — the terminal (退出码 badge) is absent.
    expect(screen.queryByText(/退出码 0/)).toBeNull();

    rerender(
      <ToolLine
        step={step({
          tool_name: "code_execute",
          arguments: { code: "print('hi')", language: "python" },
          result: "stdout:\nhello world",
          display: {
            stdout: "hello world\n",
            stderr: "",
            exit_code: 0,
            language: "python",
          },
          status: "success",
        })}
      />,
    );
    // Done: stays collapsed — 退出码 badge is expanded-only; peek shows stdout.
    expect(screen.queryByText(/退出码 0/)).toBeNull();
    expect(screen.getByText(/hello world/)).toBeTruthy();

    fireEvent.click(screen.getByText("Run code"));
    expect(screen.getByText(/退出码 0/)).toBeTruthy();
  });

  it("keeps web_search results collapsed on completion", () => {
    const { rerender } = render(
      <ToolLine
        step={step({
          tool_name: "web_search",
          arguments: { query: "深圳天气" },
          status: "running",
        })}
      />,
    );
    // The hit title is expanded-only (while running only the query detail shows).
    expect(screen.queryByText("深圳天气预报")).toBeNull();

    rerender(
      <ToolLine
        step={step({
          tool_name: "web_search",
          arguments: { query: "深圳天气" },
          result: "1 result",
          display: {
            query: "深圳天气",
            results: [
              {
                title: "深圳天气预报",
                url: "https://w.example.com",
                site: "w.example.com",
                snippet: "多云转晴",
              },
            ],
          },
          status: "success",
        })}
      />,
    );
    // Collapsed: hit title hidden; click reveals the result card.
    expect(screen.queryByText("深圳天气预报")).toBeNull();
    fireEvent.click(screen.getByText("Search web"));
    expect(screen.getByText("深圳天气预报")).toBeTruthy();
  });

  it("inlines web_search result count into the title row when collapsed", () => {
    const { rerender } = render(
      <ToolLine
        step={step({
          tool_name: "web_search",
          arguments: { query: "深圳天气" },
          status: "running",
        })}
      />,
    );
    rerender(
      <ToolLine
        step={step({
          tool_name: "web_search",
          arguments: { query: "深圳天气" },
          result: "1 result",
          display: {
            query: "深圳天气",
            results: [
              {
                title: "深圳天气预报",
                url: "https://w.example.com",
                site: "w.example.com",
                snippet: "多云转晴",
              },
            ],
          },
          status: "success",
        })}
      />,
    );
    // Already collapsed by default — 计数并入标题行（对齐 read_url 组的「· N sources」），
    // 不再另起一行 peek；结果卡标题隐藏。
    expect(screen.getByText(/1 result/)).toBeTruthy();
    expect(screen.queryByText("深圳天气预报")).toBeNull();
  });

  it("keeps str_replace diff collapsed on the running→done edge", () => {
    const { rerender } = render(
      <ToolLine
        step={step({
          tool_name: "str_replace",
          arguments: {
            path: "src/foo.ts",
            old_string: "const x = 1",
            new_string: "const x = 2",
          },
          status: "running",
        })}
      />,
    );
    // Collapsed peek only — the diff's +/- counts are expanded-only.
    expect(screen.queryByText("+1")).toBeNull();

    rerender(
      <ToolLine
        step={step({
          tool_name: "str_replace",
          arguments: {
            path: "src/foo.ts",
            old_string: "const x = 1",
            new_string: "const x = 2",
          },
          result: "已编辑 src/foo.ts",
          status: "success",
        })}
      />,
    );
    expect(screen.queryByText("+1")).toBeNull();
    expect(screen.queryByText("-1")).toBeNull();

    fireEvent.click(screen.getByText("Edit file"));
    expect(screen.getByText("+1")).toBeTruthy();
    expect(screen.getByText("-1")).toBeTruthy();
  });

  it("keeps file_write content card collapsed on the running→done edge", () => {
    const { rerender } = render(
      <ToolLine
        step={step({
          tool_name: "file_write",
          arguments: { path: "src/new.ts", content: "export const x = 1" },
          status: "running",
        })}
      />,
    );
    // Line-count footer is expanded-only (collapsed peek reads「已写入 …」).
    expect(screen.queryByText(/1 行 ·/)).toBeNull();

    rerender(
      <ToolLine
        step={step({
          tool_name: "file_write",
          arguments: { path: "src/new.ts", content: "export const x = 1" },
          result: "已写入 src/new.ts",
          status: "success",
        })}
      />,
    );
    expect(screen.queryByText(/1 行 ·/)).toBeNull();

    fireEvent.click(screen.getByText("Write file"));
    expect(screen.getByText(/1 行 ·/)).toBeTruthy();
  });

  it("suppresses the peek for consult_memory — only the self-sufficient title shows", () => {
    const { rerender } = render(
      <ToolLine
        step={step({
          tool_name: "consult_memory",
          arguments: { name: "部署流程" },
          status: "running",
        })}
      />,
    );
    rerender(
      <ToolLine
        step={step({
          tool_name: "consult_memory",
          arguments: { name: "部署流程" },
          result: "用 pnpm dev 起前端",
          display: { topic: "部署流程" },
          status: "success",
        })}
      />,
    );
    // 查阅类工具的标题已自解释（查阅记忆 部署流程）、正文一键即达 → 折叠态不再另起 peek 行。
    // The note body (expanded-only) never renders, and the topic shows exactly once (the title
    // detail — no duplicate peek line echoing it).
    expect(screen.queryByText(/用 pnpm dev 起前端/)).toBeNull();
    expect(screen.getAllByText("部署流程")).toHaveLength(1);
  });

  it("suppresses the peek for consult_skill — the summary shows only when expanded", () => {
    render(
      <ToolLine
        step={step({
          tool_name: "consult_skill",
          arguments: { name: "debate_and_review" },
          result: "完整能力指引正文…",
          display: {
            skill_name: "debate_and_review",
            summary: "对需对抗性多视角思考的问题用 debate 工具发起结构化辩论",
          },
          status: "success",
        })}
      />,
    );
    // 折叠态只留标题（查阅能力 debate_and_review）——summary 不再作为 peek 行出现，展开卡片里才有。
    expect(screen.getByText("debate_and_review")).toBeTruthy();
    expect(
      screen.queryByText(/对需对抗性多视角思考的问题用 debate 工具/),
    ).toBeNull();
  });

  it("keeps update_synthesis draft out of the title and suppresses the ack peek", () => {
    const draft = [
      "## 进展简报",
      "**当前状态**: 法律分析已完成",
      "| 队员 | 状态 |",
      "| --- | --- |",
      "| 法律分析 | ✅ 完成 |",
    ].join("\n");
    const ack = "已更新合成草稿（341 字），用户可见「进展中」预览。";
    render(
      <ToolLine
        step={step({
          tool_name: "update_synthesis",
          arguments: { draft },
          result: ack,
          status: "success",
        })}
      />,
    );
    expect(screen.getByText("Update synthesis")).toBeTruthy();
    expect(screen.queryByText(/进展简报/)).toBeNull();
    expect(screen.queryByText(/法律分析已完成/)).toBeNull();
    // 折叠态：协调 ack 不再作 peek；展开后才见结果正文。
    expect(screen.queryByText(ack)).toBeNull();
    fireEvent.click(screen.getByText("Update synthesis"));
    expect(screen.getByText(ack)).toBeTruthy();
  });

  it("suppresses file_read / file_list result-first-line peeks", () => {
    const { rerender } = render(
      <ToolLine
        step={step({
          tool_name: "file_read",
          arguments: { path: "lv_jasmine_report/lv_jasmine_synthesis.md" },
          result: "# LV诉茉莉奶白案：四路分析交叉验证与综合研判\n\n正文…",
          status: "success",
        })}
      />,
    );
    expect(screen.getByText("Read file")).toBeTruthy();
    expect(
      screen.getByText("lv_jasmine_report/lv_jasmine_synthesis.md"),
    ).toBeTruthy();
    expect(screen.queryByText(/四路分析交叉验证/)).toBeNull();

    rerender(
      <ToolLine
        step={step({
          id: "call_2",
          tool_name: "file_list",
          arguments: { path: "lv_jasmine_report" },
          result: "f lv_jasmine_report/lv_jasmine_cultural.md\nf other.md",
          status: "success",
        })}
      />,
    );
    expect(screen.getByText("List dir")).toBeTruthy();
    expect(screen.getByText("lv_jasmine_report")).toBeTruthy();
    expect(screen.queryByText(/lv_jasmine_cultural/)).toBeNull();
  });

  it("chips run_id for resolve_escalation without dumping answer or ack peek", () => {
    const ack = "已将裁决回传给 worker run_legal_1，队员将据此继续。";
    render(
      <ToolLine
        step={step({
          tool_name: "resolve_escalation",
          arguments: {
            run_id: "run_legal_1",
            answer: "请按公司法 §20 继续，详细论述如下……\n第二段。",
          },
          result: ack,
          status: "success",
        })}
      />,
    );
    expect(screen.getByText("Resolve escalate")).toBeTruthy();
    expect(screen.getByText("run_legal_1")).toBeTruthy();
    expect(screen.queryByText(/请按公司法/)).toBeNull();
    expect(screen.queryByText(ack)).toBeNull();
  });

  it("leaves read_url collapsed on completion (same default as every other tool)", () => {
    const { rerender } = render(
      <ToolLine
        step={step({
          tool_name: "read_url",
          arguments: { url: "https://weather.example.com/sz" },
          status: "running",
        })}
      />,
    );
    rerender(
      <ToolLine
        step={step({
          tool_name: "read_url",
          arguments: { url: "https://weather.example.com/sz" },
          result: '{"url":"…","title":"深圳天气","content":"正文"}',
          display: {
            url: "https://weather.example.com/sz",
            title: "深圳天气",
            site: "weather.example.com",
            snippet: "多云",
            content: "正文预览不应自动展开",
          },
          status: "success",
        })}
      />,
    );
    // Collapsed peek shows「标题 · 域名」; body stays hidden until the user expands.
    expect(screen.getByText("深圳天气 · weather.example.com")).toBeTruthy();
    expect(screen.queryByText(/正文预览不应自动展开/)).toBeNull();
  });
});

describe("ToolLineGroup · read_url 来源集合", () => {
  const sources = [
    readUrlStep("r1", {
      url: "https://zhuanlan.zhihu.com/p/1050596771_121124370",
      title: "相对论入门",
      site: "zhuanlan.zhihu.com",
      snippet: "时空弯曲简介",
    }),
    readUrlStep("r2", {
      url: "https://baike.baidu.com/item/相对论",
      title: "相对论_百度百科",
      site: "baike.baidu.com",
      snippet: "物理学理论",
    }),
  ];

  it("merges ≥2 read_url into a count-title header without collapsed pills", () => {
    renderWithTooltip(<ToolLineGroup tools={sources} isStreaming={false} />);
    expect(screen.getByText("Read page · 2 sources")).toBeTruthy();
    // 折叠态收敛为纯标题行（对齐工具组 / 思考过程）——来源 pills 移到展开态，不再平铺。
    expect(screen.queryByText("zhuanlan.zhihu.com")).toBeNull();
    expect(screen.queryByText("baike.baidu.com")).toBeNull();
    // Merged view does not inline page bodies.
    expect(screen.queryByText(/正文不应出现在合并态/)).toBeNull();
  });

  it("expands to a SourceCards-style list without body content", () => {
    renderWithTooltip(<ToolLineGroup tools={sources} isStreaming={false} />);
    fireEvent.click(screen.getByText("Read page · 2 sources"));
    expect(screen.getByText("相对论入门")).toBeTruthy();
    expect(screen.getByText("相对论")).toBeTruthy(); // cleanSourceTitle strips _百度百科
    expect(screen.getByText("时空弯曲简介")).toBeTruthy();
    // 来源域名在展开态才出现（折叠态已无 pills）。
    expect(screen.getByText("zhuanlan.zhihu.com")).toBeTruthy();
    expect(screen.queryByText(/正文不应出现在合并态/)).toBeNull();
  });

  it("leaves a mixed tool group on the default chevron path", () => {
    render(
      <ToolLineGroup
        tools={[
          sources[0],
          step({
            id: "s1",
            tool_name: "web_search",
            arguments: { query: "天气" },
            result: "1 条",
            status: "success",
          }),
        ]}
        isStreaming={false}
      />,
    );
    // Default group summary (not the source-collection header).
    expect(screen.queryByText("Read page · 2 sources")).toBeNull();
    expect(screen.getByText(/Read page 1 · Search web 1/)).toBeTruthy();
  });
});

describe("ToolLineGroup · web_search 平铺", () => {
  function searchStep(
    id: string,
    query: string,
    resultCount: number,
  ): ToolStep {
    return step({
      id,
      tool_name: "web_search",
      arguments: { query },
      result: `${resultCount} results`,
      display: {
        query,
        results: Array.from({ length: resultCount }, (_, i) => ({
          title: `${query} hit ${i + 1}`,
          url: `https://example.com/${id}/${i}`,
          site: "example.com",
          snippet: "snippet",
        })),
      },
      status: "success",
    });
  }

  it("flattens ≥2 web_search into top-level rows without an outer group shell", () => {
    render(
      <ToolLineGroup
        tools={[
          searchStep("s1", "AgentCore 架构", 10),
          searchStep("s2", "Multi-Agent 协作", 10),
        ]}
        isStreaming={false}
      />,
    );
    // No concatenated outer summary (the old「Search web A · B」shell).
    expect(
      screen.queryByText(/Search web AgentCore 架构 · Multi-Agent 协作/),
    ).toBeNull();
    // Each search is a top-level row with its own query.
    expect(screen.getByText("AgentCore 架构")).toBeTruthy();
    expect(screen.getByText("Multi-Agent 协作")).toBeTruthy();
    // Result cards stay collapsed until the individual row is opened.
    expect(screen.queryByText("AgentCore 架构 hit 1")).toBeNull();
  });

  it("keeps a mixed search+other group on the default chevron path", () => {
    render(
      <ToolLineGroup
        tools={[
          searchStep("s1", "天气", 3),
          step({
            id: "c1",
            tool_name: "code_execute",
            arguments: { code: "1+1" },
            result: "2",
            status: "success",
          }),
        ]}
        isStreaming={false}
      />,
    );
    expect(screen.getByText(/Search web 1 · Run code 1/)).toBeTruthy();
  });
});

describe("ToolLineGroup · 混杂组浏览器 CTA", () => {
  function browserStep(id: string, over?: Partial<ToolStep>): ToolStep {
    return step({
      id,
      tool_name: "browser_navigate",
      arguments: { url: "https://example.com" },
      result: "ok",
      status: "success",
      ...over,
    });
  }

  it("shows a single group-header CTA for mixed browser+other groups", () => {
    render(
      <ToolLineGroup
        tools={[
          browserStep("b1"),
          step({
            id: "c1",
            tool_name: "code_execute",
            arguments: { code: "1+1" },
            result: "2",
            status: "success",
          }),
        ]}
        isStreaming={false}
        conversationId="c1"
      />,
    );
    const ctas = screen.getAllByText("打开浏览器");
    expect(ctas).toHaveLength(1);
    fireEvent.click(ctas[0]);
    expect(showBrowser).toHaveBeenCalledTimes(1);
  });

  it("labels the CTA 查看直播 when any step is running", () => {
    render(
      <ToolLineGroup
        tools={[
          browserStep("b1", { status: "running", result: null }),
          step({
            id: "c1",
            tool_name: "code_execute",
            arguments: { code: "1+1" },
            result: "2",
            status: "success",
          }),
        ]}
        isStreaming={true}
        conversationId="c1"
      />,
    );
    expect(screen.getByText("查看直播")).toBeTruthy();
    expect(screen.queryByText("打开浏览器")).toBeNull();
  });

  it("does not show a browser CTA for pure non-browser groups", () => {
    render(
      <ToolLineGroup
        tools={[
          step({
            id: "c1",
            tool_name: "code_execute",
            arguments: { code: "1+1" },
            result: "2",
            status: "success",
          }),
          step({
            id: "f1",
            tool_name: "file_read",
            arguments: { path: "a.ts" },
            result: "ok",
            status: "success",
          }),
        ]}
        isStreaming={false}
        conversationId="c1"
      />,
    );
    expect(screen.queryByText("打开浏览器")).toBeNull();
    expect(screen.queryByText("查看直播")).toBeNull();
  });
});

describe("toolDetail · title chip", () => {
  it("prefers path / name / run_id over long prose bodies", () => {
    expect(toolDetail({ path: "a/b.md", draft: "## 长草稿\n更多" })).toBe(
      "a/b.md",
    );
    expect(toolDetail({ name: "部署流程" })).toBe("部署流程");
    expect(toolDetail({ run_id: "run_1", answer: "很长的裁决正文……" })).toBe(
      "run_1",
    );
  });

  it("does not leak update_synthesis draft into the title", () => {
    expect(
      toolDetail({
        draft: "## 进展简报\n| 队员 | 状态 |\n| --- | --- |",
      }),
    ).toBe("");
  });

  it("still chips a short one-line code snippet", () => {
    expect(toolDetail({ code: "print(1)" })).toBe("print(1)");
    expect(toolDetail({ code: "line1\nline2\nline3\nline4\nline5" })).toBe("");
  });
});

describe("toolGroupSummary · read_url", () => {
  it("uses a count title instead of URL basenames", () => {
    const tools = [
      step({
        id: "a",
        tool_name: "read_url",
        arguments: {
          url: "https://zhuanlan.zhihu.com/p/1050596771_121124370",
        },
      }),
      step({
        id: "b",
        tool_name: "read_url",
        arguments: { url: "https://baike.baidu.com/item/相对论" },
      }),
    ];
    expect(toolGroupSummary(tools)).toBe("Read page · 2 sources");
    expect(toolGroupSummary(tools)).not.toMatch(/1050596771/);
  });

  it("keeps basename titles for other same-kind groups", () => {
    const tools = [
      step({
        id: "a",
        tool_name: "file_read",
        arguments: { path: "src/foo.ts" },
      }),
      step({
        id: "b",
        tool_name: "file_read",
        arguments: { path: "src/bar.ts" },
      }),
    ];
    expect(toolGroupSummary(tools)).toBe("Read file foo.ts · bar.ts");
  });
});
