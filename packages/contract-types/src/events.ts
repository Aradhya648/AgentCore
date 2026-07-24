// SSE event contract — shared source for desktop + mobile folds (前端技术与架构 §十二).
// Event names: backend EventType → eventTypes.generated.ts
// Payload shapes: backend payloads/*.py → events.generated.ts (`pnpm gen:types`)

import type { SSEEventType } from "./eventTypes.generated";

export type { SSEEventType } from "./eventTypes.generated";
export * from "./events.generated";

export interface SSEEvent<T = unknown> {
  type: SSEEventType;
  timestamp: string;
  payload: T;
}
