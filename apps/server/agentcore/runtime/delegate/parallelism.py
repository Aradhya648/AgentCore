"""Post-checkpoint partial parallelism for delegate DAGs.

Default is conservative (honor ``depends_on`` as declared). When configured
``balanced`` / ``aggressive``, linear chains after a ``checkpoint_after`` node are
widened so independent mid-wave work can fan out — addressing fully-serial
build pipelines where only the checkpoint product is a true gate.

Modes:
- conservative: no rewrite
- balanced: keep first hop after checkpoint serial; fan middle siblings; join at leaf
- aggressive: fan all non-leaf post-checkpoint nodes off the checkpoint; join at leaf
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from agentcore.core.logging import get_logger
from agentcore.runtime.runs.plan import RunPlan

logger = get_logger(__name__)

ParallelismMode = Literal["conservative", "balanced", "aggressive"]
_VALID = frozenset({"conservative", "balanced", "aggressive"})


def resolve_parallelism(
    explicit: object,
    *,
    complexity_hint: str = "standard",
    node_count: int = 0,
    has_checkpoint: bool = False,
) -> ParallelismMode:
    """Resolve parallelism mode. Default conservative; explicit wins when valid.

    ``complexity_hint`` / ``node_count`` / ``has_checkpoint`` are reserved for
    callers that want scale-aware defaults (e.g. ops overlay); the built-in
    default stays conservative so serial plans never silently widen.
    """
    del complexity_hint, node_count, has_checkpoint  # reserved for scale overlays
    if isinstance(explicit, str) and explicit.strip() in _VALID:
        return explicit.strip()  # type: ignore[return-value]
    return "conservative"


def _children_map(plan: RunPlan) -> dict[str, list[str]]:
    children: dict[str, list[str]] = defaultdict(list)
    for node in plan.nodes:
        for dep in node.depends_on:
            children[dep].append(node.run_id)
    return children


def _linear_chain_from(start: str, children: dict[str, list[str]]) -> list[str]:
    """Follow the unique-child path from ``start``. Stops at branch or leaf."""
    chain = [start]
    cur = start
    while True:
        kids = children.get(cur) or []
        if len(kids) != 1:
            break
        chain.append(kids[0])
        cur = kids[0]
    return chain


def _is_pure_linear_chain(plan: RunPlan, chain: list[str]) -> bool:
    """True when each non-first node depends solely on its predecessor."""
    by_id = {n.run_id: n for n in plan.nodes}
    for i in range(1, len(chain)):
        node = by_id.get(chain[i])
        if node is None or list(node.depends_on) != [chain[i - 1]]:
            return False
    return True


def widen_post_checkpoint_deps(plan: RunPlan, mode: ParallelismMode) -> int:
    """Rewrite linear post-checkpoint chains per ``mode``. Returns edges changed."""
    if mode == "conservative" or not plan.nodes:
        return 0

    children = _children_map(plan)
    by_id = {n.run_id: n for n in plan.nodes}
    checkpoint_ids = [n.run_id for n in plan.nodes if n.checkpoint_after]
    if not checkpoint_ids:
        return 0

    changed = 0
    for cp_id in checkpoint_ids:
        chain = _linear_chain_from(cp_id, children)
        # Need checkpoint + ≥3 successors to have a middle fan-out opportunity.
        if len(chain) < 4 or not _is_pure_linear_chain(plan, chain):
            continue

        if mode == "balanced":
            # C → A → {B, D, …} → last
            anchor = chain[1]
            middle = chain[2:-1]
            last = chain[-1]
            if not middle:
                continue
            for mid in middle:
                node = by_id[mid]
                if list(node.depends_on) != [anchor]:
                    node.depends_on = [anchor]
                    changed += 1
            last_node = by_id[last]
            if list(last_node.depends_on) != list(middle):
                last_node.depends_on = list(middle)
                changed += 1
        else:  # aggressive
            # C → {A, B, D, …} → last
            workers = chain[1:-1]
            last = chain[-1]
            if not workers:
                continue
            for wid in workers:
                node = by_id[wid]
                if list(node.depends_on) != [cp_id]:
                    node.depends_on = [cp_id]
                    changed += 1
            last_node = by_id[last]
            if list(last_node.depends_on) != list(workers):
                last_node.depends_on = list(workers)
                changed += 1

    if changed:
        logger.info(
            "delegate.parallelism_widened",
            mode=mode,
            edges_changed=changed,
            checkpoints=checkpoint_ids,
        )
    return changed
