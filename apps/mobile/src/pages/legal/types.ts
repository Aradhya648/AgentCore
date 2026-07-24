/** Identifiers for in-app legal documents shown on login / 关于. */
export type LegalDocId = "terms" | "privacy" | "notice";

export interface LegalSection {
  heading: string;
  paragraphs: string[];
  bullets?: string[];
}

export interface LegalDocument {
  id: LegalDocId;
  title: string;
  updatedAt: string;
  sections: LegalSection[];
}
