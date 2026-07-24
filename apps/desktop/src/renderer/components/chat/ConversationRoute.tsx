import { ConversationPage } from "@/pages/ConversationPage";

/**
 * Layout route for draft (`/`) and open chat (`/conversations/:id`).
 *
 * Both child routes render this same element so ConversationPage + MessageInput stay
 * mounted across first-send navigation — avoids remount side-effects (history reload,
 * composer cleanup) when a draft promotes to a persisted conversation.
 */
export function ConversationRoute() {
  return <ConversationPage />;
}
