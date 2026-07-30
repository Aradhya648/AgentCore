import { toMessageDetail } from "@/api/conversations";
import type { components } from "@/types/api.generated";
import { describe, expect, it } from "vitest";

type Row = components["schemas"]["MessageDetail"];

function baseRow(over: Partial<Row> = {}): Row {
  return {
    id: "m1",
    role: "assistant",
    content: "见 #r1",
    reasoning_content: null,
    conversation_id: "c1",
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("toMessageDetail evidence_ledger", () => {
  it("maps REST evidence_ledger onto MessageDetail.evidenceLedger", () => {
    const m = toMessageDetail(
      baseRow({
        evidence_ledger: [
          {
            id: "#r1",
            url: "https://example.com/a",
            title: "A",
            snippet: "snip",
            site: "example.com",
            date: "2026-01-01",
            tier: "media",
            query: "q",
            deep_read: false,
            registrant: "ceo",
            citable: true,
            selected: false,
            doc_kind: "",
          },
        ],
      }),
    );
    expect(m.evidenceLedger).toEqual([
      expect.objectContaining({ id: "#r1", title: "A", site: "example.com" }),
    ]);
  });

  it("omits evidenceLedger when REST column is empty", () => {
    expect(
      toMessageDetail(baseRow({ evidence_ledger: [] })).evidenceLedger,
    ).toBeUndefined();
    expect(toMessageDetail(baseRow()).evidenceLedger).toBeUndefined();
  });
});
