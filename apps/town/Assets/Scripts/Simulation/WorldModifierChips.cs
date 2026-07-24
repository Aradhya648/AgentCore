using System.Collections.Generic;

namespace AgentTown.Simulation
{
    public enum ModifierChipTone
    {
        Neutral,
        Warn,
        Positive,
    }

    public readonly struct WorldModifierChip
    {
        public readonly string Id;
        public readonly string Label;
        public readonly ModifierChipTone Tone;

        public WorldModifierChip(string id, string label, ModifierChipTone tone)
        {
            Id = id;
            Label = label;
            Tone = tone;
        }
    }

    /// <summary>Human-readable chips for the observation HUD — port of Desktop <c>worldModifiers.ts</c>.</summary>
    public static class WorldModifierChips
    {
        public static List<WorldModifierChip> From(WorldModifiers modifiers)
        {
            var chips = new List<WorldModifierChip>();
            if (modifiers == null)
            {
                return chips;
            }

            if (modifiers.StormActive)
            {
                chips.Add(new WorldModifierChip("storm", "暴风雨", ModifierChipTone.Warn));
            }

            if (modifiers.FestivalActive)
            {
                chips.Add(new WorldModifierChip("festival", "节庆", ModifierChipTone.Positive));
            }

            if (modifiers.MarketPriceMultiplier > 1.01)
            {
                chips.Add(new WorldModifierChip(
                    "price",
                    $"物价 ×{modifiers.MarketPriceMultiplier:0.0}",
                    ModifierChipTone.Warn));
            }

            if (modifiers.SquareAttractionBoost > 0.01)
            {
                int pct = (int)System.Math.Round(modifiers.SquareAttractionBoost * 100.0);
                chips.Add(new WorldModifierChip(
                    "square",
                    $"广场吸引力 +{pct}%",
                    ModifierChipTone.Positive));
            }

            return chips;
        }

        /// <summary>Also surface active world-event titles as chips when modifiers alone are quiet.</summary>
        public static void AppendActiveEvents(List<WorldModifierChip> chips, IReadOnlyList<WorldEvent> events)
        {
            if (chips == null || events == null)
            {
                return;
            }

            for (int i = 0; i < events.Count; i++)
            {
                WorldEvent evt = events[i];
                if (evt == null)
                {
                    continue;
                }

                string id = string.IsNullOrEmpty(evt.EventId) ? $"evt-{i}" : evt.EventId;
                string label = !string.IsNullOrEmpty(evt.Title)
                    ? evt.Title
                    : !string.IsNullOrEmpty(evt.EventType)
                        ? evt.EventType
                        : evt.Kind;
                if (string.IsNullOrEmpty(label))
                {
                    continue;
                }

                bool duplicate = false;
                for (int c = 0; c < chips.Count; c++)
                {
                    if (chips[c].Label == label || chips[c].Id == id)
                    {
                        duplicate = true;
                        break;
                    }
                }

                if (!duplicate)
                {
                    chips.Add(new WorldModifierChip(id, label, ModifierChipTone.Neutral));
                }
            }
        }
    }
}
