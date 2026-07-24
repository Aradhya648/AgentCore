"""S1/S2 ratchets: durable kind single-source + per-kind codec exhaustiveness.

S1 — :class:`SuspensionKind` values derive from :data:`DURABLE_INTERACTION_KINDS`
(itself a subset of :class:`InteractionKind`); no hand-copied string drift.

S2 — every :class:`SuspensionKind` has exactly one :class:`SuspensionKindCodec`
(frame extras + summary projection). Adding a durable kind without registering
a codec fails this test.
"""

from agentcore.runtime.interaction import InteractionKind
from agentcore.runtime.suspension import (
    DURABLE_INTERACTION_KINDS,
    SUSPENSION_KIND_CODECS,
    SuspensionKind,
)


def test_durable_kinds_subset_of_interaction_kind():
    """S1: durable set ⊆ InteractionKind (by value + member identity)."""
    interaction_by_value = {k.value: k for k in InteractionKind}
    for kind in DURABLE_INTERACTION_KINDS:
        assert isinstance(kind, InteractionKind)
        assert kind in InteractionKind
        assert interaction_by_value[kind.value] is kind


def test_suspension_kind_mirrors_durable_interaction_kinds():
    """S1: SuspensionKind value set == DURABLE_INTERACTION_KINDS value set."""
    suspension_values = {k.value for k in SuspensionKind}
    durable_values = {k.value for k in DURABLE_INTERACTION_KINDS}
    assert suspension_values == durable_values
    for sk in SuspensionKind:
        assert InteractionKind(sk.value) in DURABLE_INTERACTION_KINDS
        assert sk.value == InteractionKind(sk.value).value


def test_kind_codecs_cover_all_suspension_kinds():
    """S2: codec registry is exhaustive and consistent with SuspensionKind."""
    assert set(SUSPENSION_KIND_CODECS) == set(SuspensionKind)
    for kind, codec in SUSPENSION_KIND_CODECS.items():
        assert codec.kind is kind
        assert codec.cls.kind is kind
        assert callable(codec.frame_extras)
        assert callable(codec.from_extras)
        assert callable(codec.summary_extras)


def test_codec_classes_are_unique_per_kind():
    """S2: one concrete subclass per durable kind (no double registration)."""
    classes = [codec.cls for codec in SUSPENSION_KIND_CODECS.values()]
    assert len(classes) == len(set(classes))
