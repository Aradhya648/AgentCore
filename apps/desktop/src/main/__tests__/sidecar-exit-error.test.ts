import { describe, expect, it } from "vitest";
import { formatSidecarExitError } from "../sidecar-service";

describe("formatSidecarExitError", () => {
  it("surfaces ImportError from stderr instead of bare exit code", () => {
    const stderr = `Traceback (most recent call last):
  File "agentcore/sidecar/__main__.py", line 27, in <module>
    from agentcore.sidecar.server import SidecarServer
ImportError: cannot import name 'run_chat_pipeline' from partially initialized module 'agentcore.runtime.pipeline'`;

    const err = formatSidecarExitError(1, stderr);
    expect(err.message).toBe(
      "sidecar 启动失败：cannot import name 'run_chat_pipeline' from partially initialized module 'agentcore.runtime.pipeline'",
    );
  });

  it("falls back to exit code when stderr has no parseable error", () => {
    const err = formatSidecarExitError(1, "");
    expect(err.message).toBe("sidecar 进程退出（code 1）");
  });

  it("uses the last exception line from a traceback", () => {
    const stderr = `Traceback (most recent call last):
  File "x.py", line 1, in <module>
    raise ValueError("bad config")
ValueError: bad config`;

    const err = formatSidecarExitError(1, stderr);
    expect(err.message).toBe("sidecar 启动失败：ValueError: bad config");
  });
});
