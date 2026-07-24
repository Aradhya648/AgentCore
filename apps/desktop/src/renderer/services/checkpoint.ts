import type { CheckpointDecision } from "@/types/events";

/** Decisions a user can actively make on an ask_user card. `timeout` is
 * engine-only (no-answer deadline) and is never sent by the client.
 *
 * Settlement is cold `POST .../resume` (services/turns.ts `runResume`); the
 * shared ask_user body ({@link AskUserCard}) is reused by ResumePrompt. */
export type CheckpointUserDecision = Exclude<CheckpointDecision, "timeout">;
