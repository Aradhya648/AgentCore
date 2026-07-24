import { ConversationReplay } from "@/components/ConversationReplay";
import { Navigate, useLocation, useNavigate, useParams } from "react-router-dom";

/** Standalone 会话复盘 route — bookmarkable `/replay/:conversationId`. */
export function ReplayPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const from =
    (location.state as { from?: string } | null)?.from ?? "/overview";

  if (!conversationId) {
    return <Navigate to="/overview" replace />;
  }

  return (
    <ConversationReplay
      conversationId={conversationId}
      backLabel="返回"
      onBack={() => navigate(from)}
    />
  );
}
