import { AskCommenceV1 } from "@/components/chat/ask/preview/AskCommenceV1";
import { AskCommenceV2 } from "@/components/chat/ask/preview/AskCommenceV2";
import { AskCommenceV3 } from "@/components/chat/ask/preview/AskCommenceV3";
import { AskCommenceV4 } from "@/components/chat/ask/preview/AskCommenceV4";
import { AskCommenceV5 } from "@/components/chat/ask/preview/AskCommenceV5";
import { ASK_COMMENCE_MOCK } from "@/preview/askCommenceMock";
import { ASK_COMMENCE_SCENES } from "@/preview/askCommenceScenes";
import { FlaskConical } from "lucide-react";
import { useSearchParams } from "react-router-dom";

/**
 * Hidden preview route (`#/preview/ask-commence`) — **已退役**开场/开工提案布局 A/B。
 * 生产 ask 已统一为通用澄清卡（V5 = {@link AskDecisionBody}）；V1–V4 仅历史对照，勿当产品手册。
 *
 * Deep-link: `#/preview/ask-commence?s=ask-commence-v5`（现生产）或 v1…v4（退役对照）。
 */
export function AskCommencePreviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const scenes = ASK_COMMENCE_SCENES;
  const requested = searchParams.get("s");
  const current = scenes.find((s) => s.id === requested) ?? scenes[0] ?? null;
  const selected = current?.id ?? null;

  const select = (id: string) => setSearchParams({ s: id }, { replace: true });

  return (
    <div
      className="flex h-full min-h-0"
      data-preview-ask-commence={selected ?? ""}
    >
      <aside className="flex w-80 shrink-0 flex-col border-r border-border">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <FlaskConical size={18} className="shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-base font-semibold text-foreground">
              已退役 · ask 开场布局对照
            </h1>
            <p className="text-xs text-muted-foreground">
              生产 = 通用澄清卡；V1–V4 仅历史对照
            </p>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <ul className="space-y-0.5">
            {scenes.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => select(s.id)}
                  className={`w-full rounded-lg px-3 py-2.5 text-left ${
                    selected === s.id
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  }`}
                >
                  <span className="block truncate text-sm font-medium">
                    {s.title}
                  </span>
                  <span className="mt-0.5 block font-mono text-xs text-muted-foreground">
                    {s.id}
                  </span>
                  <span className="mt-1 block text-xs leading-snug text-muted-foreground">
                    {s.intent}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="border-b border-border px-4 py-2">
          <p className="truncate text-sm font-medium text-foreground">
            {current
              ? `${current.title} · ${current.paradigm}`
              : "选择一套方案"}
          </p>
          {current && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {current.intent}
            </p>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto bg-muted/10 p-6">
          <div className="mx-auto w-full max-w-3xl">
            {selected === "ask-commence-v1" && (
              <AskCommenceV1 content={ASK_COMMENCE_MOCK} />
            )}
            {selected === "ask-commence-v2" && (
              <AskCommenceV2 content={ASK_COMMENCE_MOCK} />
            )}
            {selected === "ask-commence-v3" && (
              <AskCommenceV3 content={ASK_COMMENCE_MOCK} />
            )}
            {selected === "ask-commence-v4" && (
              <AskCommenceV4 content={ASK_COMMENCE_MOCK} />
            )}
            {selected === "ask-commence-v5" && (
              <AskCommenceV5 content={ASK_COMMENCE_MOCK} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
