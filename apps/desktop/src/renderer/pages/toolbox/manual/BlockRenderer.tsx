import { Suspense } from "react";
import { resolveEmbed } from "./embedRegistry";
import { resolveManualIcon } from "./icons";
import {
  BoundaryTable,
  Bullets,
  Callout,
  CardGrid,
  DoDont,
  Faq,
  InfoCard,
  Lead,
  SettingsRows,
  Steps,
} from "./primitives";
import { renderRichText } from "./renderRichText";
import type { FaqAnswerPart, ManualBlock } from "./types";

export function BlockRenderer({ block }: { block: ManualBlock }) {
  switch (block.type) {
    case "lead":
      return <Lead>{renderRichText(block.text)}</Lead>;
    case "paragraph":
      return block.emphasis ? (
        <p className="text-sm font-medium text-foreground">
          {renderRichText(block.text)}
        </p>
      ) : (
        <p className="text-sm leading-relaxed text-muted-foreground">
          {renderRichText(block.text)}
        </p>
      );
    case "callout":
      return (
        <Callout variant={block.variant}>{renderRichText(block.text)}</Callout>
      );
    case "cards":
      return (
        <CardGrid cols={block.cols ?? 2}>
          {block.items.map((item) => {
            const Icon = item.icon ? resolveManualIcon(item.icon) : null;
            return (
              <InfoCard
                key={item.title}
                title={item.title}
                desc={item.desc}
                highlight={item.highlight}
                icon={Icon ? <Icon size={16} /> : undefined}
              />
            );
          })}
        </CardGrid>
      );
    case "bullets":
      return (
        <Bullets
          items={block.items.map((b) => ({
            title: b.title,
            desc: renderRichText(b.desc),
          }))}
        />
      );
    case "steps":
      return (
        <Steps
          items={block.items.map((s) => ({
            title: s.title,
            desc: renderRichText(s.desc),
          }))}
        />
      );
    case "doDont":
      return (
        <DoDont
          good={{ label: block.good.label, items: block.good.items }}
          bad={{ label: block.bad.label, items: block.bad.items }}
        />
      );
    case "faq":
      return (
        <Faq
          items={block.items.map((f) => ({
            q: f.q,
            a: <FaqAnswer parts={f.a} />,
          }))}
        />
      );
    case "boundaryTable":
      return <BoundaryTable rows={block.rows} />;
    case "settingsRows":
      return <SettingsRows rows={block.rows} />;
    case "embed": {
      const Comp = resolveEmbed(block.key);
      if (!Comp) {
        return (
          <p className="text-xs text-muted-foreground">
            未注册的嵌入组件：{block.key}
          </p>
        );
      }
      return (
        <div data-manual-embed={block.key}>
          <Suspense
            fallback={
              <div className="h-32 animate-pulse rounded-xl bg-muted/40" />
            }
          >
            <Comp />
          </Suspense>
        </div>
      );
    }
    default: {
      const _exhaustive: never = block;
      return _exhaustive;
    }
  }
}

function FaqAnswer({ parts }: { parts: FaqAnswerPart[] }) {
  return (
    <div className="space-y-2">
      {parts.map((part, i) => {
        if (part.type === "boundaryTable") {
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: 静态 FAQ 片段
            <BoundaryTable key={i} rows={part.rows} />
          );
        }
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: 静态 FAQ 片段
          <div key={i}>{renderRichText(part.text)}</div>
        );
      })}
    </div>
  );
}
