"""RFC 5987 Content-Disposition helpers for file downloads."""

from urllib.parse import quote


def download_headers(filename: str, *, fallback: str = "download") -> dict[str, str]:
    """Content-Disposition for a download, with an RFC 5987 UTF-8 ``filename*``.

    A bare ``filename=`` cannot carry non-ASCII (e.g. Chinese) names under latin-1
    header encoding; ``filename*=UTF-8''<pct-encoded>`` does, with a sanitized ASCII
    ``filename=`` fallback for older clients.
    """
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or fallback
    quoted = quote(filename, safe="")
    return {
        "Content-Disposition": (
            f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"
        )
    }
