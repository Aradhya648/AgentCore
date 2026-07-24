// @vitest-environment jsdom
/**
 * 结构重算不得把 layoutReady 打回 false（否则 GraphView 卸载 ReactFlow → 整图闪烁）。
 * 实测高度变化走防抖二次 ELK，避免每帧重排。
 */
import { HEIGHT_RELAYOUT_DEBOUNCE_MS, NODE_HEIGHT } from "@/lib/elk-layout";
import type { Execution } from "@/stores/execution";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const computeLayout = vi.fn();

vi.mock("@/lib/elk-layout", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/elk-layout")>();
  return {
    ...actual,
    computeLayout: (...args: unknown[]) => computeLayout(...args),
  };
});

import { useGraphLayout } from "../useGraphLayout";

function exec(runIds: string[]): Execution {
  return {
    runs: [
      {
        id: "captain",
        kind: "captain",
        dependsOn: [],
        agentId: "ceo",
        task: "",
        status: "running",
        parentRunId: null,
        replacesRunId: null,
      },
      ...runIds.map((id) => ({
        id,
        kind: "agent" as const,
        dependsOn: [] as string[],
        agentId: id,
        task: id,
        status: "running" as const,
        parentRunId: null,
        replacesRunId: null,
      })),
    ],
  } as unknown as Execution;
}

describe("useGraphLayout · keep graph during relayout", () => {
  beforeEach(() => {
    computeLayout.mockReset();
    let n = 0;
    computeLayout.mockImplementation(async (nodeIds: string[]) => {
      n += 1;
      const positions: Record<string, { x: number; y: number }> = {};
      for (const id of nodeIds) {
        positions[id] = { x: n * 10, y: n * 20 };
      }
      return {
        positions,
        width: 400 + n,
        height: 300 + n,
        groups: [],
      };
    });
  });

  it("keeps layoutReady true across structural append (追加委派)", async () => {
    const emptyExpand = new Set<string>();
    const { result, rerender } = renderHook(
      ({ execution }: { execution: Execution }) =>
        useGraphLayout(execution, "tree", "view", emptyExpand),
      { initialProps: { execution: exec(["w1"]) } },
    );

    await waitFor(() => expect(result.current.layoutReady).toBe(true));
    const readySnapshots: boolean[] = [];

    await act(async () => {
      rerender({ execution: exec(["w1", "w2"]) });
      // 同步读：结构 effect 已跑但 ELK 未完成时不得 blank。
      readySnapshots.push(result.current.layoutReady);
    });

    expect(readySnapshots.every((v) => v)).toBe(true);
    await waitFor(() => {
      expect(result.current.layoutReady).toBe(true);
      expect(Object.keys(result.current.positions)).toEqual(
        expect.arrayContaining(["w1", "w2"]),
      );
    });
  });
});

describe("useGraphLayout · measured-height secondary ELK", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    computeLayout.mockReset();
    let n = 0;
    computeLayout.mockImplementation(
      async (
        nodeIds: string[],
        _edges: unknown,
        _layout: unknown,
        _bookends: unknown,
        _subTeams: unknown,
        _spacing: unknown,
        nodeSizes: Record<string, { width: number; height: number }>,
      ) => {
        n += 1;
        const positions: Record<string, { x: number; y: number }> = {};
        let y = 0;
        for (const id of nodeIds) {
          positions[id] = { x: n * 10, y };
          y += (nodeSizes?.[id]?.height ?? NODE_HEIGHT) + 56;
        }
        return {
          positions,
          width: 400 + n,
          height: y + 24,
          groups: [],
        };
      },
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces height patches into one secondary ELK with measured sizes", async () => {
    const emptyExpand = new Set<string>();
    const { result } = renderHook(() =>
      useGraphLayout(exec(["be", "fe"]), "leftright", "view", emptyExpand),
    );

    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });
    await waitFor(() => expect(result.current.layoutReady).toBe(true));
    const afterStructural = computeLayout.mock.calls.length;
    expect(afterStructural).toBeGreaterThanOrEqual(1);

    await act(async () => {
      result.current.onNodesChange([
        {
          type: "dimensions",
          id: "be",
          dimensions: { width: 210, height: 180 },
        },
        {
          type: "dimensions",
          id: "fe",
          dimensions: { width: 210, height: 200 },
        },
      ]);
    });
    // Still within debounce window — no secondary ELK yet.
    expect(computeLayout.mock.calls.length).toBe(afterStructural);

    await act(async () => {
      result.current.onNodesChange([
        {
          type: "dimensions",
          id: "be",
          dimensions: { width: 210, height: 190 },
        },
      ]);
    });
    expect(computeLayout.mock.calls.length).toBe(afterStructural);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(HEIGHT_RELAYOUT_DEBOUNCE_MS + 20);
    });

    await waitFor(() =>
      expect(computeLayout.mock.calls.length).toBe(afterStructural + 1),
    );

    const lastSizes = computeLayout.mock.calls.at(-1)?.[6] as Record<
      string,
      { width: number; height: number }
    >;
    expect(lastSizes.be.height).toBe(190);
    expect(lastSizes.fe.height).toBe(200);
    expect(result.current.nodeSizes.be.height).toBe(190);
    expect(result.current.nodeSizes.fe.height).toBe(200);
  });

  it("does not re-ELK when measured heights already match nodeSizes", async () => {
    const emptyExpand = new Set<string>();
    const { result } = renderHook(() =>
      useGraphLayout(exec(["be"]), "leftright", "view", emptyExpand),
    );

    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });
    await waitFor(() => expect(result.current.layoutReady).toBe(true));

    await act(async () => {
      result.current.onNodesChange([
        {
          type: "dimensions",
          id: "be",
          dimensions: { width: 210, height: 160 },
        },
      ]);
      await vi.advanceTimersByTimeAsync(HEIGHT_RELAYOUT_DEBOUNCE_MS + 20);
    });
    await waitFor(() => expect(result.current.nodeSizes.be?.height).toBe(160));
    const afterSecondary = computeLayout.mock.calls.length;

    await act(async () => {
      // Same height again — gate should skip another ELK.
      result.current.onNodesChange([
        {
          type: "dimensions",
          id: "be",
          dimensions: { width: 210, height: 160 },
        },
      ]);
      await vi.advanceTimersByTimeAsync(HEIGHT_RELAYOUT_DEBOUNCE_MS + 20);
    });

    expect(computeLayout.mock.calls.length).toBe(afterSecondary);
  });
});
