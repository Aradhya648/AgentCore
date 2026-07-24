import type { LegalDocId } from "./types";
import { getLegalDoc } from "./content";

/** Scrollable legal document body — used by login overlay and 设置·关于. */
export function LegalDocBody({ docId }: { docId: LegalDocId }) {
  const doc = getLegalDoc(docId);
  if (!doc) {
    return <p className="text-sm text-muted-foreground">未找到该文档。</p>;
  }

  return (
    <article className="space-y-6 text-sm text-foreground">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">{doc.title}</h1>
        <p className="text-xs text-muted-foreground">更新日期：{doc.updatedAt}</p>
      </header>

      {doc.sections.map((section) => (
        <section key={section.heading} className="space-y-2">
          <h2 className="text-sm font-semibold">{section.heading}</h2>
          {section.paragraphs[0] ? (
            <p className="leading-relaxed text-muted-foreground">
              {section.paragraphs[0]}
            </p>
          ) : null}
          {section.bullets && section.bullets.length > 0 ? (
            <ul className="list-disc space-y-1.5 pl-5 text-muted-foreground">
              {section.bullets.map((item) => (
                <li key={item} className="leading-relaxed">
                  {item}
                </li>
              ))}
            </ul>
          ) : null}
          {section.paragraphs.slice(1).map((p) => (
            <p key={p} className="leading-relaxed text-muted-foreground">
              {p}
            </p>
          ))}
        </section>
      ))}
    </article>
  );
}
