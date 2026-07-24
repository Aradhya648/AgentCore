"""Repository owner-scope guards (SEC-002).

User-facing data access on the per-user aggregates (conversation / board / folder)
makes ``user_id`` a *required* argument so multi-tenant isolation is the structural
default, not a caller convention. Cross-owner access is allowed only through
explicitly-named ``*_unscoped`` methods (trusted internal / admin callers).

Two guards:
  * an AST signature check (no DB, always runs) that locks the required-``user_id`` shape
    so a future edit can't silently re-introduce an optional ``user_id`` default; and
  * a behavioural cross-user check (real PostgreSQL, auto-skips without it) that pins the
    actual scoping and the unscoped escape hatch.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agentcore.db.repositories import (
    BoardRepository,
    ConversationRepository,
    FolderRepository,
    UserRepository,
)

_REPO_DIR = Path(__file__).resolve().parents[2] / "agentcore" / "db" / "repositories"

# repo file -> (class, methods that MUST require user_id, explicit unscoped hatches).
_CONTRACT: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "conversations.py": (
        "ConversationRepository",
        ("get_by_id", "update_title", "soft_delete",
         "set_pinned", "set_archived"),
        ("get_by_id_unscoped", "update_title_unscoped"),
    ),
    "boards.py": (
        "BoardRepository",
        ("get_by_id", "get_by_conversation_id", "update_meta", "save_scene",
         "attach_conversation", "soft_delete"),
        (),
    ),
    "folders.py": (
        "FolderRepository",
        ("get_by_id", "update", "soft_delete"),
        ("get_by_id_unscoped",),
    ),
}

_FuncDef = ast.AsyncFunctionDef | ast.FunctionDef


def _methods(file_name: str, class_name: str) -> dict[str, _FuncDef]:
    tree = ast.parse((_REPO_DIR / file_name).read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return {m.name: m for m in cls.body if isinstance(m, ast.AsyncFunctionDef | ast.FunctionDef)}


def _user_id_required(fn: _FuncDef) -> bool:
    """True iff ``user_id`` is a keyword-only arg with no default (mandatory)."""
    for arg, default in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True):
        if arg.arg == "user_id":
            return default is None
    return False


def _has_user_id(fn: _FuncDef) -> bool:
    args = (*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs)
    return any(a.arg == "user_id" for a in args)


def test_user_facing_methods_require_user_id() -> None:
    """Every user-facing read/mutate on the four per-user aggregates requires user_id.

    Locks SEC-002's structural default: a regression to ``user_id: str | None = None``
    (the old caller-convention shape) turns this red.
    """
    offenders: dict[str, list[str]] = {}
    for file_name, (class_name, scoped, _unscoped) in _CONTRACT.items():
        methods = _methods(file_name, class_name)
        for name in scoped:
            fn = methods.get(name)
            if fn is None or not _user_id_required(fn):
                offenders.setdefault(file_name, []).append(name)
    assert offenders == {}, f"user_id must be a required kw-only arg: {offenders}"


def test_unscoped_methods_are_explicit() -> None:
    """The cross-owner escape hatches exist and take no user_id (explicitly unscoped)."""
    offenders: dict[str, list[str]] = {}
    for file_name, (class_name, _scoped, unscoped) in _CONTRACT.items():
        methods = _methods(file_name, class_name)
        for name in unscoped:
            fn = methods.get(name)
            if fn is None or _has_user_id(fn):
                offenders.setdefault(file_name, []).append(name)
    assert offenders == {}, f"unscoped methods must exist and take no user_id: {offenders}"


async def test_get_by_id_is_owner_scoped(session_factory) -> None:
    """A non-owner is treated as absent; the owner sees the row; unscoped bypasses.

    Pins the actual SEC-002 behaviour across the per-user aggregates (the AST guards
    above only lock the signature shape).
    """
    async with session_factory() as s:
        a = (await UserRepository(s).create(username="own-a", display_name="A")).user_id
        b = (await UserRepository(s).create(username="own-b", display_name="B")).user_id

    async with session_factory() as s:
        conv = await ConversationRepository(s).create(user_id=a, title="a's chat")
        folder = await FolderRepository(s).create(user_id=a, name="a's folder")
        board = await BoardRepository(s).create(user_id=a, title="a's board")

    async with session_factory() as s:
        conv_repo = ConversationRepository(s)
        folder_repo = FolderRepository(s)
        board_repo = BoardRepository(s)

        # The owner sees their own rows.
        assert await conv_repo.get_by_id(conv.id, user_id=a) is not None
        assert await folder_repo.get_by_id(folder.id, user_id=a) is not None
        assert await board_repo.get_by_id(board.id, user_id=a) is not None

        # A different user is treated as absent (route → 404, no existence leak).
        assert await conv_repo.get_by_id(conv.id, user_id=b) is None
        assert await folder_repo.get_by_id(folder.id, user_id=b) is None
        assert await board_repo.get_by_id(board.id, user_id=b) is None

        # Trusted internal callers can still cross owners via the explicit hatch.
        assert await conv_repo.get_by_id_unscoped(conv.id) is not None
        assert await folder_repo.get_by_id_unscoped(folder.id) is not None
