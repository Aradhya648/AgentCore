import {
  type DevicePlatform,
  registerDevice,
  unregisterDevice,
} from "@/api/devices";
// Native (Capacitor) push notification integration (原生推送, 前端技术与架构 §七).
//
// The backend already pushes a 需要你 notification when an agent durably pauses
// (runtime/suspension_persistence.py _notify_pause → push/notify.py notify_user), carrying
// deep-link data {conversation_id, message_id, kind}. This module is the missing client
// half: register the device's FCM token with /v1/devices, and on a notification tap
// deep-link to the paused conversation.
//
// Native-only — every entry no-ops on web (a browser has no FCM), mirroring secureStorage.ts:
// the plugin import is bundled but its native calls only run behind isNativePlatform(), so a
// web build never invokes it.
import { Capacitor } from "@capacitor/core";
import {
  type ActionPerformed,
  PushNotifications,
  type Token,
} from "@capacitor/push-notifications";

// The FCM token last reported by the OS, remembered so logout can unregister it server-side
// (DELETE /v1/devices). Null until the 'registration' event fires.
let currentToken: string | null = null;

function platform(): DevicePlatform {
  // Capacitor.getPlatform() returns ios | android | web — exactly the backend's closed set.
  return Capacitor.getPlatform() as DevicePlatform;
}

/**
 * Wire the push listeners ONCE at startup (from <PushBridge/>, inside the router):
 *  - 'registration'                    → an FCM token arrived; remember it + upsert it to
 *                                        the current user. Fires only after enablePush()
 *                                        calls register() (i.e. while authenticated), so the
 *                                        bearer POST succeeds.
 *  - 'registrationError'               → forget any cached token (nothing to unregister).
 *  - 'pushNotificationActionPerformed' → the user tapped a notification (incl. cold start);
 *                                        deep-link to its conversation.
 *
 * `onOpenConversation` is injected rather than importing the router, so navigation stays in
 * the React tree. Returns a cleanup that removes the listeners (a no-op on web).
 */
export async function initPush(
  onOpenConversation: (conversationId: string) => void,
): Promise<() => void> {
  if (!Capacitor.isNativePlatform()) return () => {};

  const registration = await PushNotifications.addListener(
    "registration",
    (token: Token) => {
      currentToken = token.value;
      // Best-effort: a failed upsert just means "no push this session", never a crash.
      void registerDevice(token.value, platform()).catch(() => {});
    },
  );
  const registrationError = await PushNotifications.addListener(
    "registrationError",
    () => {
      currentToken = null;
    },
  );
  const action = await PushNotifications.addListener(
    "pushNotificationActionPerformed",
    (event: ActionPerformed) => {
      const conversationId = event.notification.data?.conversation_id;
      if (typeof conversationId === "string" && conversationId) {
        onOpenConversation(conversationId);
      }
    },
  );

  return () => {
    void registration.remove();
    void registrationError.remove();
    void action.remove();
  };
}

/**
 * Request notification permission and register with FCM (the token then arrives via the
 * 'registration' listener). Call when authenticated (fresh login / restored session). No-op
 * on web or if the user declines permission — push degrades to "off", never blocks the app.
 */
export async function enablePush(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  try {
    let perm = await PushNotifications.checkPermissions();
    if (perm.receive === "prompt" || perm.receive === "prompt-with-rationale") {
      perm = await PushNotifications.requestPermissions();
    }
    if (perm.receive !== "granted") return;
    await PushNotifications.register();
  } catch {
    // Permission / registration failure degrades to "no push", never breaks the session.
  }
}

/**
 * Unregister this device server-side on logout so a signed-out phone stops receiving the
 * previous user's notifications. Best-effort; MUST run BEFORE the bearer tokens are cleared
 * (the DELETE is authenticated).
 */
export async function disablePush(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  const token = currentToken;
  currentToken = null;
  if (!token) return;
  try {
    await unregisterDevice(token);
  } catch {
    // A failed unregister just leaves a stale token the backend prunes on its next push.
  }
}
