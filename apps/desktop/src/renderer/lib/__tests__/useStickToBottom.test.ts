// @vitest-environment jsdom
import { useStickToBottom } from "@/lib/useStickToBottom";
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("useStickToBottom followOnReset", () => {
  it("re-sticks to bottom when followOnReset is true (default)", () => {
    const { result, rerender } = renderHook(
      ({ contentKey, resetKey }) => useStickToBottom(contentKey, resetKey),
      { initialProps: { contentKey: "a", resetKey: "run-1" } },
    );

    const el = document.createElement("div");
    Object.defineProperty(el, "scrollHeight", {
      value: 800,
      configurable: true,
    });
    Object.defineProperty(el, "clientHeight", {
      value: 200,
      configurable: true,
    });
    el.scrollTo = ((opts: ScrollToOptions) => {
      el.scrollTop = opts.top ?? 0;
    }) as typeof el.scrollTo;

    act(() => {
      (result.current.scrollRef as { current: HTMLDivElement | null }).current =
        el;
    });

    rerender({ contentKey: "b", resetKey: "run-2" });
    expect(result.current.atBottom).toBe(true);
    expect(el.scrollTop).toBe(800);
  });

  it("opens at top and stays detached when followOnReset is false", () => {
    const { result, rerender } = renderHook(
      ({ contentKey, resetKey, follow }) =>
        useStickToBottom(contentKey, resetKey, { followOnReset: follow }),
      {
        initialProps: {
          contentKey: "a",
          resetKey: "run-1",
          follow: false as boolean,
        },
      },
    );

    const el = document.createElement("div");
    Object.defineProperty(el, "scrollHeight", {
      value: 800,
      configurable: true,
    });
    Object.defineProperty(el, "clientHeight", {
      value: 200,
      configurable: true,
    });
    el.scrollTop = 400;
    el.scrollTo = ((opts: ScrollToOptions) => {
      el.scrollTop = opts.top ?? 0;
    }) as typeof el.scrollTo;

    act(() => {
      (result.current.scrollRef as { current: HTMLDivElement | null }).current =
        el;
    });

    rerender({ contentKey: "b", resetKey: "run-2", follow: false });
    expect(result.current.atBottom).toBe(false);
    expect(el.scrollTop).toBe(0);
  });
});
