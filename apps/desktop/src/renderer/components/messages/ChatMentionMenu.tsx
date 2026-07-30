import { Button } from "@/components/ui";
import { Users } from "lucide-react";
import { useEffect, useRef } from "react";
import { avatarInitial } from "./chatDisplay";

/** One row in the IM @-person menu (not the AI-chat file mention menu). */
export type ChatMentionMenuItem =
  | { kind: "everyone"; label: string }
  | {
      kind: "user";
      userId: string;
      label: string;
      subtitle?: string;
    };

interface Props {
  items: ChatMentionMenuItem[];
  activeIndex: number;
  query: string;
  onHover: (index: number) => void;
  onSelect: (item: ChatMentionMenuItem) => void;
}

/**
 * Floating listbox for IM `@` mentions. Separate from the conversation-page
 * file {@link MentionMenu} — different data source and selection semantics.
 */
export function ChatMentionMenu({
  items,
  activeIndex,
  query,
  onHover,
  onSelect,
}: Props) {
  const listRef = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const el = list.children[activeIndex] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  return (
    <div
      className="absolute bottom-full left-0 z-20 mb-2 w-full max-w-sm overflow-hidden rounded-xl border border-border bg-popover text-popover-foreground shadow-lg"
      aria-label="@ 提及"
    >
      {items.length === 0 ? (
        <p className="px-3 py-3 text-sm text-muted-foreground">
          {query ? `没有匹配「${query}」的成员` : "没有可提及的成员"}
        </p>
      ) : (
        <ul ref={listRef} className="max-h-56 overflow-y-auto py-1">
          {items.map((item, i) => {
            const active = i === activeIndex;
            return (
              <li key={item.kind === "everyone" ? "everyone" : item.userId}>
                <Button
                  variant="ghost"
                  aria-current={active ? "true" : undefined}
                  onMouseEnter={() => onHover(i)}
                  onClick={() => onSelect(item)}
                  className={`h-auto w-full justify-start gap-2 rounded-none px-3 py-2 font-normal ${
                    active ? "bg-accent text-accent-foreground" : ""
                  }`}
                >
                  {item.kind === "everyone" ? (
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                      <Users size={14} />
                    </span>
                  ) : (
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                      {avatarInitial(item.label)}
                    </span>
                  )}
                  <span className="min-w-0 flex-1 text-left">
                    <span className="block truncate text-sm text-foreground">
                      {item.kind === "everyone" ? `@${item.label}` : item.label}
                    </span>
                    {item.kind === "user" && item.subtitle ? (
                      <span className="block truncate text-xs text-muted-foreground">
                        {item.subtitle}
                      </span>
                    ) : item.kind === "everyone" ? (
                      <span className="block truncate text-xs text-muted-foreground">
                        通知会话内所有成员
                      </span>
                    ) : null}
                  </span>
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
