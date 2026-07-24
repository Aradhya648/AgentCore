// @vitest-environment jsdom
import { teamHasStartedRuns } from "@/components/chat/InlineTeamGraph";
import { planCapabilities } from "@/components/graph/planCapabilities";
import { replayFixtureNow } from "@/preview/replay";
import {
  assistantProjectionId,
  getRuntime,
  useConversationStore,
} from "@/stores/conversation";
import { projectRuntime, useExecutionStore } from "@/stores/execution";
import { loadFixtures } from "@agentcore/protocol-conformance";
import { afterEach, describe, expect, it } from "vitest";

afterEach(() => {
  const cid = "preview-multi_agent_debate";
  useConversationStore.getState().dropConversationRuntime(cid);
  useExecutionStore.setState({ byId: {} });
});

describe("preview replay · InlineTeamGraph prerequisites", () => {
  it("keys execution so chat default surface can mount", () => {
    const fixture = loadFixtures().find((f) => f.name === "multi_agent_debate");
    expect(fixture).toBeTruthy();
    if (!fixture) return;

    const cid = "preview-multi_agent_debate";
    replayFixtureNow(cid, fixture.events, fixture.description);

    const rt = getRuntime(cid);
    const roles = rt.messages.map((m) => `${m.role}:${m.content.slice(0, 40)}`);
    expect(roles, `messages=${JSON.stringify(roles)}`).toEqual(
      expect.arrayContaining([expect.stringMatching(/^assistant:/)]),
    );

    const assistant = [...rt.messages]
      .reverse()
      .find((m) => m.role === "assistant");
    expect(assistant).toBeTruthy();
    if (!assistant) return;

    const key = assistantProjectionId(assistant);
    const execRt = useExecutionStore.getState().byId[key];
    expect(
      execRt,
      `execution.byId missing key=${key}; have=${Object.keys(useExecutionStore.getState().byId).join(",")}`,
    ).toBeTruthy();
    if (!execRt) return;

    const execution = projectRuntime(execRt);
    expect(execution).toBeTruthy();
    if (!execution) return;
    expect(planCapabilities(execution.planType).showsTeamGraph).toBe(true);
    expect(teamHasStartedRuns(execution.runs)).toBe(true);
    expect(execution.id).toBe(assistant.executionId);
  });
});
