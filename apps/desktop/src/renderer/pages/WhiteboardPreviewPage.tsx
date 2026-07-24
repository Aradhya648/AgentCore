import { WHITEBOARD_SCENES } from "@/preview/whiteboardScenes";
import { type WhiteboardApi, WhiteboardCanvas } from "@/whiteboard";
import { FlaskConical } from "lucide-react";
import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Hidden dev route (`#/preview/whiteboard`) for eyeballing the self-built whiteboard canvas
 * offline (AI协作白板.md §六). The SSE preview (`#/preview`) replays event vectors into the chat
 * surface; the whiteboard is a separate canvas whose "vector" is a scene, so this companion
 * surface mounts the REAL {@link WhiteboardCanvas} with each committed scene from
 * {@link WHITEBOARD_SCENES} — no backend, no LLM. Scenario selection is URL-driven
 * (`?s=<id>`) so the screenshot harness (scripts/shoot-whiteboard.mjs) can deep-link each and
 * humans can bookmark one. Reachable by typing the URL; not in the nav.
 */
export function WhiteboardPreviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const apiRef = useRef<WhiteboardApi | null>(null);

  const scenes = WHITEBOARD_SCENES;
  const requested = searchParams.get("s");
  const current = scenes.find((s) => s.id === requested) ?? scenes[0] ?? null;
  const selected = current?.id ?? null;

  const select = (id: string) => setSearchParams({ s: id }, { replace: true });

  // After a scene mounts (remounted per selection via key), frame its content so every
  // scene — authored near different coordinates — lands centered for the screenshot.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-fit whenever the selection changes.
  useEffect(() => {
    const t = setTimeout(() => apiRef.current?.zoomToFit(), 120);
    return () => clearTimeout(t);
  }, [selected]);

  return (
    <div className="flex h-full min-h-0" data-preview-board={selected ?? ""}>
      <aside className="flex w-72 shrink-0 flex-col border-r border-border">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <FlaskConical size={18} className="shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-base font-semibold text-foreground">
              白板预览
            </h1>
            <p className="text-xs text-muted-foreground">
              {scenes.length} 个场景 · 离线回放
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
                  className={`w-full rounded-lg px-3 py-2 text-left ${
                    selected === s.id
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  }`}
                >
                  <span className="block truncate text-sm font-medium">
                    {s.id}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {s.description}
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
            {current?.id ?? "选择一个场景"}
          </p>
          {current && (
            <p className="truncate text-xs text-muted-foreground">
              {current.description}
            </p>
          )}
        </div>
        <div className="relative min-h-0 flex-1">
          {current ? (
            <WhiteboardCanvas
              key={current.id}
              ref={apiRef}
              initialElements={current.elements}
              initialSelectedIds={current.selectedIds}
              onChange={() => {}}
              onOrganizeSelection={() => {}}
              onImplementSelection={() => {}}
              onIterateArtifact={() => {}}
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
