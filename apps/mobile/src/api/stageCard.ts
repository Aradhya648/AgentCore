/** Resolve stage_card via streaming POST (同桌面 resolveStageCardConversation). */
import { apiUrl, authHeader } from "@/api/client";
import { pumpSSEForTests } from "@/api/stream";
import { StreamHttpError } from "@/lib/errors";
import type { SSEEvent } from "@agentcore/contract-types";

async function streamErrorFromResponse(
  response: Response,
): Promise<StreamHttpError> {
  let code: string | undefined;
  let serverMessage: string | undefined;
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string };
      detail?: { code?: string; message?: string };
    };
    code = body.error?.code ?? body.detail?.code;
    serverMessage = body.error?.message ?? body.detail?.message;
  } catch {
    /* non-JSON */
  }
  return new StreamHttpError(response.status, code, serverMessage);
}

export async function resolveStageCardStream(
  conversationId: string,
  stageCardId: string,
  body: {
    decision: "start_debate" | "research_first";
    note?: string;
    motionOverride?: string | null;
  },
  onEvent: (event: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const path = `/v1/conversations/${conversationId}/interactions/${stageCardId}`;
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...authHeader(),
    },
    body: JSON.stringify({
      kind: "stage_card",
      decision: body.decision,
      note: body.note ?? "",
      motion_override: body.motionOverride ?? null,
    }),
    signal,
  });
  if (!response.ok) throw await streamErrorFromResponse(response);
  await pumpSSEForTests(response, onEvent, conversationId);
}
