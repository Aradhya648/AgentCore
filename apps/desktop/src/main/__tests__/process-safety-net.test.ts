import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  app: { exit: vi.fn() },
}));

import { isTransientNetworkError } from "../process-safety-net";

describe("isTransientNetworkError", () => {
  it("matches Chromium net::ERR_CONNECTION_CLOSED", () => {
    expect(
      isTransientNetworkError(new Error("net::ERR_CONNECTION_CLOSED")),
    ).toBe(true);
  });

  it("matches other Chromium net errors", () => {
    expect(
      isTransientNetworkError(new Error("net::ERR_NAME_NOT_RESOLVED")),
    ).toBe(true);
    expect(
      isTransientNetworkError(new Error("net::ERR_INTERNET_DISCONNECTED")),
    ).toBe(true);
    expect(isTransientNetworkError(new Error("net::ERR_TIMED_OUT"))).toBe(true);
  });

  it("matches bare ERR_CONNECTION_* without net:: prefix", () => {
    expect(isTransientNetworkError(new Error("ERR_CONNECTION_CLOSED"))).toBe(
      true,
    );
  });

  it("matches Node errno codes", () => {
    expect(
      isTransientNetworkError(
        Object.assign(new Error("connect"), { code: "ECONNRESET" }),
      ),
    ).toBe(true);
    expect(
      isTransientNetworkError(
        Object.assign(new Error("getaddrinfo"), { code: "ENOTFOUND" }),
      ),
    ).toBe(true);
  });

  it("rejects non-network errors", () => {
    expect(isTransientNetworkError(new Error("Cannot read properties"))).toBe(
      false,
    );
    expect(isTransientNetworkError(new TypeError("x is not a function"))).toBe(
      false,
    );
    expect(
      isTransientNetworkError(
        Object.assign(new Error("disk"), { code: "ENOENT" }),
      ),
    ).toBe(false);
  });
});
