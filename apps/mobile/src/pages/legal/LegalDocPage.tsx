import { Navigate, useNavigate, useParams } from "react-router-dom";
import { LegalDocBody } from "./LegalDocBody";
import { getLegalDoc } from "./content";
import type { LegalDocId } from "./types";
import "@/pages/more/more.css";

/**
 * Public legal reader (`/legal/:docId`) — reachable from login without auth.
 * Optional `from` query is unused; back always prefers history, else /login.
 */
export function LegalDocPage() {
  const { docId } = useParams<{ docId: string }>();
  const navigate = useNavigate();
  const doc = getLegalDoc(docId);

  if (!doc) return <Navigate to="/login" replace />;

  return (
    <div className="screen">
      <header className="bar">
        <button type="button" className="link" onClick={() => navigate(-1)}>
          ← 返回
        </button>
        <span>{doc.title}</span>
        <span style={{ width: 44 }} />
      </header>
      <div className="legal-scroll">
        <LegalDocBody docId={doc.id as LegalDocId} />
      </div>
    </div>
  );
}
