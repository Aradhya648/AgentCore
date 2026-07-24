import { FileText, Folder } from "lucide-react";
import type React from "react";
import { useEffect, useRef, useState } from "react";

export function InlineRow({
  indent,
  icon,
  children,
}: {
  indent: number;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      className="flex items-center gap-1.5 rounded-lg pr-1 text-xs"
      style={{ paddingLeft: indent }}
    >
      <span className="w-[13px] shrink-0" aria-hidden="true" />
      <span className="shrink-0 text-muted-foreground">{icon}</span>
      {children}
    </div>
  );
}

export function InlineCreateRow({
  kind,
  depth,
  indentBase = 0,
  onSubmit,
  onCancel,
}: {
  kind: "file" | "dir";
  depth: number;
  indentBase?: number;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  return (
    <li>
      <InlineRow
        indent={depth * 14 + 8 + indentBase}
        icon={kind === "dir" ? <Folder size={13} /> : <FileText size={13} />}
      >
        <InlineInput initial="" onSubmit={onSubmit} onCancel={onCancel} />
      </InlineRow>
    </li>
  );
}

export function InlineInput({
  initial,
  onSubmit,
  onCancel,
}: {
  initial: string;
  onSubmit: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initial);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);

  return (
    <input
      ref={ref}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSubmit(value);
        else if (e.key === "Escape") onCancel();
      }}
      onBlur={onCancel}
      className="my-0.5 h-5 min-w-0 flex-1 rounded border border-primary/50 bg-background px-1 text-xs outline-none"
    />
  );
}
