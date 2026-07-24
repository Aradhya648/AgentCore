import { StageCard } from "@/components/chat/StageCard";
import { useConversationStore } from "@/stores/conversation";
import { useInteractionStore } from "@/stores/interactions";
import type { InteractionEntry } from "@/stores/interactions";
/** Surface pending stage_card interactions above the composer (chip 升级位).
 * Align mobile ChatPage: Dock only mounts pending; historical resolved/orphaned
 * from journal reload must not stack. Optionally flash the newest terminal
 * briefly as a short confirmation, then fold away. */
import { useEffect, useMemo, useRef, useState } from "react";

/** How long a just-settled card stays visible as a confirmation flash. */
const TERMINAL_FLASH_MS = 4000;

export function StageCardDock() {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const byId = useInteractionStore((s) => s.byId);
  const [flashId, setFlashId] = useState<string | null>(null);
  const prevStatusRef = useRef<Map<string, InteractionEntry["status"]>>(
    new Map(),
  );

  const pending = useMemo(() => {
    if (!conversationId) return [] as InteractionEntry[];
    const out: InteractionEntry[] = [];
    for (const e of byId.values()) {
      if (e.conversationId !== conversationId) continue;
      if (e.kind !== "stage_card") continue;
      if (e.status !== "pending" && e.status !== "submitting") continue;
      out.push(e);
    }
    return out;
  }, [byId, conversationId]);

  // Detect pending/submitting → terminal transitions while Dock is mounted
  // (not journal hydrate of already-terminal history).
  useEffect(() => {
    if (!conversationId) {
      prevStatusRef.current = new Map();
      return;
    }
    const prev = prevStatusRef.current;
    const next = new Map<string, InteractionEntry["status"]>();
    let newestTerminal: string | null = null;
    for (const e of byId.values()) {
      if (e.conversationId !== conversationId || e.kind !== "stage_card") {
        continue;
      }
      next.set(e.id, e.status);
      const wasLive =
        prev.get(e.id) === "pending" || prev.get(e.id) === "submitting";
      const nowTerminal = e.status === "resolved" || e.status === "orphaned";
      if (wasLive && nowTerminal) newestTerminal = e.id;
    }
    prevStatusRef.current = next;
    if (newestTerminal) setFlashId(newestTerminal);
  }, [byId, conversationId]);

  useEffect(() => {
    if (!flashId) return;
    const t = window.setTimeout(() => setFlashId(null), TERMINAL_FLASH_MS);
    return () => window.clearTimeout(t);
  }, [flashId]);

  const flashEntry =
    flashId && conversationId
      ? (() => {
          const e = byId.get(flashId);
          if (
            !e ||
            e.conversationId !== conversationId ||
            e.kind !== "stage_card"
          ) {
            return null;
          }
          if (e.status !== "resolved" && e.status !== "orphaned") return null;
          // Don't duplicate if still pending somehow.
          if (pending.some((p) => p.id === e.id)) return null;
          return e;
        })()
      : null;

  const entries = flashEntry ? [...pending, flashEntry] : pending;
  if (!entries.length) return null;
  return (
    <div className="space-y-2 px-4 pb-2" data-testid="stage-card-dock">
      {entries.map((e) => (
        <StageCard key={e.id} entry={e} />
      ))}
    </div>
  );
}
