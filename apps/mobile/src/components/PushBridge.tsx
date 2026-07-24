import { initPush } from "@/api/push";
// Mounts the native push listeners inside the router so a notification tap can navigate
// (原生推送 deep-link, 前端技术与架构 §七). Renders nothing; native-only (initPush no-ops on
// web). Mounted unconditionally at the App root (even during the auth-loading splash) so a
// cold-start tap — the app launched FROM a notification — still deep-links once the webview
// is up.
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

export function PushBridge() {
  const navigate = useNavigate();
  useEffect(() => {
    let cleanup: (() => void) | undefined;
    let cancelled = false;
    void initPush((conversationId) => {
      // RequireAuth bounces to /login if the session is gone; otherwise this lands on the
      // paused conversation.
      navigate(`/c/${conversationId}`);
    }).then((fn) => {
      // Unmounted before init resolved → run the cleanup immediately so no listener leaks.
      if (cancelled) fn();
      else cleanup = fn;
    });
    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [navigate]);
  return null;
}
