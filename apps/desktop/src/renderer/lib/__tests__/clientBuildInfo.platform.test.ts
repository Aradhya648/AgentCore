import { clientHeaders, clientPlatform } from "@/lib/clientBuildInfo";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("clientBuildInfo platform", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends X-Client-Platform=web in web runtime", () => {
    vi.stubGlobal("window", { __WEB__: true });
    expect(clientPlatform()).toBe("web");
    expect(clientHeaders()["X-Client-Platform"]).toBe("web");
  });

  it("sends X-Client-Platform=desktop outside web runtime", () => {
    vi.stubGlobal("window", { __WEB__: false });
    expect(clientPlatform()).toBe("desktop");
    expect(clientHeaders()["X-Client-Platform"]).toBe("desktop");
  });
});
