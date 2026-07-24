"""SSE contract validation — EventType ↔ SSEPayloadMap ↔ generated union."""

from scripts.validate_sse_contract import main


def test_sse_contract_aligned() -> None:
    main()
