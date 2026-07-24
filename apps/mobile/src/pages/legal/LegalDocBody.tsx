import { getLegalDoc } from "./content";
import type { LegalDocId } from "./types";

/** Shared body for /legal/:docId and settings entry. */
export function LegalDocBody({ docId }: { docId: LegalDocId }) {
  const doc = getLegalDoc(docId);
  if (!doc) {
    return <p className="muted">未找到该文档。</p>;
  }

  return (
    <article className="legal-article">
      <header className="legal-header">
        <h1>{doc.title}</h1>
        <p className="muted">更新日期：{doc.updatedAt}</p>
      </header>

      {doc.sections.map((section) => (
        <section key={section.heading} className="legal-section">
          <h2>{section.heading}</h2>
          {section.paragraphs[0] ? <p>{section.paragraphs[0]}</p> : null}
          {section.bullets && section.bullets.length > 0 ? (
            <ul>
              {section.bullets.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
          {section.paragraphs.slice(1).map((p) => (
            <p key={p}>{p}</p>
          ))}
        </section>
      ))}
    </article>
  );
}
