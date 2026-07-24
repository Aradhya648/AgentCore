import { Navigate, useParams } from "react-router-dom";
import { SettingsHeader } from "../more/SettingsHeader";
import { LegalDocBody } from "./LegalDocBody";
import { getLegalDoc } from "./content";
import type { LegalDocId } from "./types";

/** Authenticated settings route: /more/legal/:docId */
export function LegalSettingsPage() {
  const { docId } = useParams<{ docId: string }>();
  const doc = getLegalDoc(docId);
  if (!doc) return <Navigate to="/more/about" replace />;

  return (
    <div>
      <SettingsHeader
        title={doc.title}
        description={`更新日期：${doc.updatedAt}`}
      />
      <div className="mt-6 max-w-2xl">
        <LegalDocBody docId={doc.id as LegalDocId} />
      </div>
    </div>
  );
}
