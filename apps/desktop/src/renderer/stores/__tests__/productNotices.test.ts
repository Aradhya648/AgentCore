import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/notices", () => ({
  fetchActive: vi.fn(),
  dismissNotice: vi.fn(),
}));

import { dismissNotice, fetchActive } from "@/services/notices";
import type { ActiveNotice } from "@/services/notices";
import { useProductNoticesStore } from "../productNotices";

const fetchActiveMock = vi.mocked(fetchActive);
const dismissNoticeMock = vi.mocked(dismissNotice);

function notice(
  overrides: Partial<ActiveNotice> & Pick<ActiveNotice, "id">,
): ActiveNotice {
  return {
    title: "t",
    body: "b",
    cta_label: null,
    cta_url: null,
    dismiss_policy: "once",
    dismissed: false,
    published_at: "2026-01-01T00:00:00Z",
    severity: "normal",
    surface: "banner",
    ...overrides,
  };
}

beforeEach(() => {
  fetchActiveMock.mockReset();
  dismissNoticeMock.mockReset();
  useProductNoticesStore.setState({
    banner: null,
    modal: null,
    inbox: [],
    sessionSnoozed: [],
    loading: false,
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("productNotices store · modal", () => {
  it("refresh writes banner + modal + inbox", async () => {
    const banner = notice({ id: "b1", surface: "banner" });
    const modal = notice({ id: "m1", surface: "modal" });
    const inbox = [notice({ id: "i1", surface: "inbox" })];
    fetchActiveMock.mockResolvedValue({ banner, modal, inbox });

    await useProductNoticesStore.getState().refresh();

    const s = useProductNoticesStore.getState();
    expect(s.banner).toEqual(banner);
    expect(s.modal).toEqual(modal);
    expect(s.inbox).toEqual(inbox);
  });

  it("dismiss modal clears modal and calls API (no session snooze)", async () => {
    const modal = notice({
      id: "m1",
      surface: "modal",
      dismiss_policy: "once",
    });
    useProductNoticesStore.setState({
      modal,
      banner: notice({ id: "b1" }),
    });
    dismissNoticeMock.mockResolvedValue(undefined);
    fetchActiveMock.mockResolvedValue({
      banner: notice({ id: "b1" }),
      modal: null,
      inbox: [],
    });

    await useProductNoticesStore.getState().dismiss("m1");

    expect(dismissNoticeMock).toHaveBeenCalledWith("m1");
    expect(useProductNoticesStore.getState().modal).toBeNull();
    expect(useProductNoticesStore.getState().sessionSnoozed).toEqual([]);
    // Banner untouched when dismissing a different id.
    expect(useProductNoticesStore.getState().banner?.id).toBe("b1");
  });

  it("dismiss never banner session-snoozes only (no API)", async () => {
    const banner = notice({
      id: "b-never",
      dismiss_policy: "never",
      surface: "both",
    });
    useProductNoticesStore.setState({
      banner,
      modal: notice({ id: "m1", surface: "modal" }),
    });

    await useProductNoticesStore.getState().dismiss("b-never");

    expect(dismissNoticeMock).not.toHaveBeenCalled();
    expect(useProductNoticesStore.getState().banner).toBeNull();
    expect(useProductNoticesStore.getState().sessionSnoozed).toEqual([
      "b-never",
    ]);
    expect(useProductNoticesStore.getState().modal?.id).toBe("m1");
  });

  it("refresh respects banner session snooze but keeps modal", async () => {
    useProductNoticesStore.setState({ sessionSnoozed: ["b1"] });
    fetchActiveMock.mockResolvedValue({
      banner: notice({ id: "b1", dismiss_policy: "never" }),
      modal: notice({ id: "m1", surface: "modal" }),
      inbox: [],
    });

    await useProductNoticesStore.getState().refresh();

    expect(useProductNoticesStore.getState().banner).toBeNull();
    expect(useProductNoticesStore.getState().modal?.id).toBe("m1");
  });
});
