import sidecarIpc from "@agentcore/contract-types/sidecar-ipc.json";
import {
  type SidecarResumeRequest,
  type SidecarTurnResult,
  buildSidecarResumeRpcParams,
} from "@shared/sidecar-contract";
import { describe, expect, it } from "vitest";

/** Runtime key guard — compile-time ``SidecarTurnResult`` + contract JSON must agree. */
function assertExactKeys(obj: object, keys: readonly string[]): void {
  expect(Object.keys(obj).sort()).toEqual([...keys].sort());
}

describe("sidecar IPC contract (TS ↔ Python single source)", () => {
  it("SidecarTurnResult sample matches turnResult.keys + usageKeys", () => {
    const sample: SidecarTurnResult = {
      turnId: "t1",
      messageId: "m1",
      content: "hi",
      reasoningContent: null,
      finishReason: "stop",
      model: "deepseek-v4-flash",
      rounds: 1,
      usage: {
        inputTokens: 10,
        outputTokens: 5,
        reasoningTokens: 0,
        cacheHitTokens: 0,
        cacheMissTokens: 0,
      },
      citations: [],
      runs: null,
      error: null,
    };
    assertExactKeys(sample, sidecarIpc.turnResult.keys);
    assertExactKeys(sample.usage, sidecarIpc.turnResult.usageKeys);
  });

  it("buildSidecarResumeRpcParams emits exactly resumeRpcParams.keys", () => {
    const req: Pick<
      SidecarResumeRequest,
      | "messageId"
      | "conversationId"
      | "traceId"
      | "decision"
      | "note"
      | "selected"
      | "permissionAxes"
    > = {
      messageId: "m-asst",
      conversationId: "c1",
      traceId: "abc123",
      decision: "continue",
      note: "",
      selected: ["a"],
      permissionAxes: {
        file_write: "ask",
        command: "ask",
        team_kickoff: "rules",
      },
    };
    const withInference = buildSidecarResumeRpcParams(
      req,
      {
        baseUrl: "https://x/v1/inference/v1",
        apiKey: "tok",
        model: "deepseek-v4-flash",
      },
      { baseUrl: "http://127.0.0.1:9", token: "bridge-tok" },
    );
    assertExactKeys(withInference, sidecarIpc.resumeRpcParams.keys);
    expect(withInference.browserBridge).toEqual({
      baseUrl: "http://127.0.0.1:9",
      token: "bridge-tok",
    });

    const withoutInference = buildSidecarResumeRpcParams(req);
    assertExactKeys(withoutInference, [
      ...sidecarIpc.resumeRpcParams.keys.filter(
        (k) => k !== "inference" && k !== "browserBridge",
      ),
    ]);
    expect(withoutInference.selected).toEqual(["a"]);
    expect(withoutInference.permissionAxes).toEqual({
      file_write: "ask",
      command: "ask",
      team_kickoff: "rules",
    });

    // Explicit null clears sidecar sticky env / prior turn.
    const clearBridge = buildSidecarResumeRpcParams(req, undefined, null);
    expect(clearBridge.browserBridge).toBeNull();

    // 权限轴缺省 ⇒ 键不出现，sidecar 沿用当前值。
    const withoutAxes = buildSidecarResumeRpcParams({
      ...req,
      permissionAxes: undefined,
    });
    expect("permissionAxes" in withoutAxes).toBe(false);
  });

  it("resume IPC request required fields are a superset of renderer routing keys", () => {
    const ipcOnly = sidecarIpc.resumeIpcRequest.keys.filter(
      (k) => !sidecarIpc.resumeRpcParams.keys.includes(k),
    );
    expect(ipcOnly.sort()).toEqual(["rootId", "subpath"]);
    for (const key of sidecarIpc.resumeRpcParams.required) {
      expect(sidecarIpc.resumeIpcRequest.required).toContain(key);
    }
  });

  it("write-back maps every SidecarTurnResult persistence field to RecordTurnRequest", () => {
    const map = sidecarIpc.writeBack.resultToRecordTurn;
    const resultKeys = new Set<string>();
    for (const from of Object.keys(map)) {
      if (from.startsWith("usage.")) {
        resultKeys.add("usage");
      } else {
        resultKeys.add(from);
      }
    }
    const persistable = sidecarIpc.turnResult.keys.filter(
      (k) => !sidecarIpc.writeBack.ipcOnlyTurnResultFields.includes(k),
    );
    expect([...resultKeys].sort()).toEqual([...persistable].sort());
    expect(sidecarIpc.writeBack.contextFields).toEqual({
      traceId: "trace_id",
      userMessage: "user_message",
      optimisticUserId: "user_message_id",
    });
  });

  it("inference block keys align with SidecarInference", () => {
    const inference = {
      baseUrl: "https://x",
      apiKey: "k",
      model: "m",
    };
    assertExactKeys(inference, sidecarIpc.inference.keys);
    expect(sidecarIpc.inference.required).toEqual(sidecarIpc.inference.keys);
  });
});
