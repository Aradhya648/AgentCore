"""Chunked NDJSON framing — long lines must reassemble across small reads."""

from __future__ import annotations

import json

from agentcore.sidecar.line_buffer import append_stdout_chunk


def test_append_stdout_chunk_reassembles_oversized_line() -> None:
    payload = {"jsonrpc": "2.0", "method": "turn/event", "params": {"blob": "x" * 200_000}}
    framed = json.dumps(payload, ensure_ascii=False) + "\n"
    assert "\n" not in framed[:-1]

    buffer = ""
    emitted: list[str] = []
    chunk_size = 4096
    for i in range(0, len(framed), chunk_size):
        buffer, lines = append_stdout_chunk(buffer, framed[i : i + chunk_size])
        emitted.extend(lines)

    assert buffer == ""
    assert len(emitted) == 1
    assert json.loads(emitted[0]) == payload


def test_append_stdout_chunk_eof_remainder_left_in_buffer() -> None:
    buffer, lines = append_stdout_chunk("", '{"partial":')
    assert lines == []
    assert buffer == '{"partial":'


def test_append_stdout_chunk_multiple_lines_in_one_chunk() -> None:
    buffer, lines = append_stdout_chunk("", "a\nb\n")
    assert buffer == ""
    assert lines == ["a", "b"]
