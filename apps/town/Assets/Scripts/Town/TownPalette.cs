using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// Shared colour tables for the runtime town (ported from the retired UE
    /// <c>TownBuildingSpawner</c> / <c>TownNpcManager</c> palettes so the placeholder look
    /// matches the reference). Values are linear RGB in 0..1.
    /// </summary>
    public static class TownPalette
    {
        /// <summary>Deterministic, high-contrast NPC tints applied via <c>MaterialPropertyBlock</c>.</summary>
        public static readonly Color[] NpcColors =
        {
            new(0.90f, 0.35f, 0.35f),
            new(0.35f, 0.65f, 0.95f),
            new(0.40f, 0.85f, 0.45f),
            new(0.95f, 0.75f, 0.25f),
            new(0.75f, 0.45f, 0.90f),
            new(0.35f, 0.90f, 0.90f),
            new(0.95f, 0.55f, 0.35f),
            new(0.55f, 0.55f, 0.95f),
            new(0.85f, 0.45f, 0.55f),
            new(0.45f, 0.80f, 0.70f),
            new(0.80f, 0.80f, 0.35f),
            new(0.60f, 0.40f, 0.30f),
        };

        public static Color NpcColor(int index)
        {
            int count = NpcColors.Length;
            int wrapped = ((index % count) + count) % count;
            return NpcColors[wrapped];
        }

        /// <summary>Grass base under the whole town (Desktop <c>townGround</c> BASE_GRASS colour).</summary>
        public static readonly Color Grass = new(0.49f, 0.72f, 0.49f);

        /// <summary>
        /// Soft horizon apron beyond the walkable grass — muted so bird-corner fill
        /// reads as ground, not a second bright lawn.
        /// </summary>
        public static readonly Color HorizonFill = new(0.42f, 0.58f, 0.48f);

        /// <summary>Road / path surface tint (darker asphalt vs grass).</summary>
        public static readonly Color Road = new(0.32f, 0.34f, 0.36f);

        /// <summary>Lighter road accent (branch streets).</summary>
        public static readonly Color RoadAccent = new(0.38f, 0.40f, 0.42f);
    }
}
