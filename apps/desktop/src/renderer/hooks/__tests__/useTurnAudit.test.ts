// @vitest-environment jsdom

import {
  invalidateTurnAudit,
  resetTurnAuditCacheForTests,
  useTurnAudit,
} from "@/hooks/useTurnAudit";
import { fetchTurnAudit } from "@/services/audit";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/preview", () => ({ isWebPreview: vi.fn(() => false) }));
vi.mock("@/services/audit", () => ({ fetchTurnAudit: vi.fn() }));

beforeEach(() => {
  resetTurnAuditCacheForTests();
  vi.mocked(fetchTurnAudit).mockReset();
});

describe("useTurnAudit", () => {
  it("loads audit with include_causal once per turn", async () => {
    vi.mocked(fetchTurnAudit).mockResolvedValue({ data: [], total: 0 });
    const { result } = renderHook(() => useTurnAudit("conv-1", "msg-1"));
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(fetchTurnAudit).toHaveBeenCalledTimes(1);
    expect(fetchTurnAudit).toHaveBeenCalledWith("conv-1", "msg-1", {
      includeCausal: true,
    });
  });

  it("dedupes concurrent subscribers", async () => {
    vi.mocked(fetchTurnAudit).mockResolvedValue({ data: [], total: 0 });
    renderHook(() => useTurnAudit("conv-1", "msg-1"));
    renderHook(() => useTurnAudit("conv-1", "msg-1"));
    await waitFor(() => {
      expect(fetchTurnAudit).toHaveBeenCalledTimes(1);
    });
  });

  it("invalidateTurnAudit refetches", async () => {
    vi.mocked(fetchTurnAudit).mockResolvedValue({ data: [], total: 0 });
    const { result } = renderHook(() => useTurnAudit("conv-1", "msg-1"));
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    act(() => {
      invalidateTurnAudit("conv-1", "msg-1");
    });
    await waitFor(() => {
      expect(fetchTurnAudit).toHaveBeenCalledTimes(2);
    });
  });
});
