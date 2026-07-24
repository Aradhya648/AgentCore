import type { EvidenceLedgerEntry } from "@/types/events";
import { type ReactNode, createContext, useContext } from "react";

const EvidenceLedgerContext = createContext<ReadonlyMap<
  string,
  EvidenceLedgerEntry
> | null>(null);

/** 辩论室 / 发言 Markdown 树：把场级台账 map 传给 {@link EvidenceBadge} 解析 `#eN`。 */
export function EvidenceLedgerProvider({
  ledger,
  children,
}: {
  ledger: ReadonlyMap<string, EvidenceLedgerEntry> | null;
  children: ReactNode;
}) {
  return (
    <EvidenceLedgerContext.Provider value={ledger}>
      {children}
    </EvidenceLedgerContext.Provider>
  );
}

export function useEvidenceLedgerMap(): ReadonlyMap<
  string,
  EvidenceLedgerEntry
> | null {
  return useContext(EvidenceLedgerContext);
}
