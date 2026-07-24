using System.Collections.Generic;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Maps active world events / modifiers to in-scene feedback (banner copy + region tint).
    /// Pure helpers — no UnityEngine dependency so EditMode tests stay lightweight.
    /// </summary>
    public static class WorldEventFeedback
    {
        public readonly struct Banner
        {
            public readonly string Title;
            /// <summary>Optional subtitle from <see cref="WorldEvent.Description"/> (long narrative).</summary>
            public readonly string Subtitle;
            public readonly string ToneId;

            public Banner(string title, string toneId, string subtitle = "")
            {
                Title = title;
                Subtitle = subtitle ?? "";
                ToneId = toneId;
            }
        }

        /// <summary>
        /// Prefer the most dramatic active event (storm → price → announce → festival);
        /// fall back to modifier chips.
        /// </summary>
        public static bool TryResolveBanner(
            IReadOnlyList<WorldEvent> events,
            WorldModifiers modifiers,
            out Banner banner)
        {
            banner = default;
            if (events != null)
            {
                WorldEvent best = null;
                int bestRank = int.MaxValue;
                for (int i = 0; i < events.Count; i++)
                {
                    WorldEvent evt = events[i];
                    if (evt == null)
                    {
                        continue;
                    }

                    string title = !string.IsNullOrEmpty(evt.Title)
                        ? evt.Title
                        : !string.IsNullOrEmpty(evt.EventType)
                            ? evt.EventType
                            : evt.Kind;
                    if (string.IsNullOrEmpty(title))
                    {
                        continue;
                    }

                    int rank = DramaRank(evt.EventType, evt.Kind);
                    if (rank < bestRank)
                    {
                        bestRank = rank;
                        best = evt;
                    }
                }

                if (best != null)
                {
                    string title = !string.IsNullOrEmpty(best.Title)
                        ? best.Title
                        : !string.IsNullOrEmpty(best.EventType)
                            ? best.EventType
                            : best.Kind;
                    banner = new Banner(title, ToneFor(best.EventType, best.Kind), best.Description ?? "");
                    return true;
                }
            }

            if (modifiers != null)
            {
                if (modifiers.StormActive)
                {
                    banner = new Banner("暴风雨来袭", "storm");
                    return true;
                }

                if (modifiers.MarketPriceMultiplier > 1.01)
                {
                    banner = new Banner($"市场物价 ×{modifiers.MarketPriceMultiplier:0.0}", "price");
                    return true;
                }

                if (modifiers.FestivalActive)
                {
                    banner = new Banner("节日庆典", "festival");
                    return true;
                }
            }

            return false;
        }

        /// <summary>Lower = more dramatic (shown first on the banner).</summary>
        public static int DramaRank(string eventType, string kind)
        {
            string key = !string.IsNullOrEmpty(eventType) ? eventType : kind ?? "";
            key = key.Trim().ToLowerInvariant();
            return key switch
            {
                "storm" => 0,
                "price_surge" or "price" => 1,
                "announcement" => 2,
                "festival" => 3,
                _ => 4,
            };
        }

        /// <summary>Regions that should receive a soft highlight for the given event kind.</summary>
        public static IReadOnlyList<string> HighlightRegionsFor(string eventTypeOrKind)
        {
            string key = (eventTypeOrKind ?? "").Trim().ToLowerInvariant();
            return key switch
            {
                "festival" => new[] { "广场", "公园" },
                "storm" => new[] { "住宅区", "公园", "广场" },
                "price_surge" or "price" => new[] { "市场", "面包店" },
                "announcement" => new[] { "镇政厅", "广场" },
                _ => System.Array.Empty<string>(),
            };
        }

        public static IReadOnlyList<string> HighlightRegions(
            IReadOnlyList<WorldEvent> events,
            WorldModifiers modifiers)
        {
            var set = new HashSet<string>();
            if (events != null)
            {
                for (int i = 0; i < events.Count; i++)
                {
                    WorldEvent evt = events[i];
                    if (evt == null)
                    {
                        continue;
                    }

                    string key = !string.IsNullOrEmpty(evt.EventType) ? evt.EventType : evt.Kind;
                    IReadOnlyList<string> regions = HighlightRegionsFor(key);
                    for (int r = 0; r < regions.Count; r++)
                    {
                        set.Add(regions[r]);
                    }
                }
            }

            if (modifiers != null)
            {
                if (modifiers.StormActive)
                {
                    foreach (string id in HighlightRegionsFor("storm")) set.Add(id);
                }

                if (modifiers.FestivalActive)
                {
                    foreach (string id in HighlightRegionsFor("festival")) set.Add(id);
                }

                if (modifiers.MarketPriceMultiplier > 1.01)
                {
                    foreach (string id in HighlightRegionsFor("price_surge")) set.Add(id);
                }

                if (modifiers.SquareAttractionBoost > 0.01)
                {
                    set.Add("广场");
                }
            }

            if (set.Count == 0)
            {
                return System.Array.Empty<string>();
            }

            var list = new List<string>(set);
            list.Sort();
            return list;
        }

        public static string ToneFor(string eventType, string kind)
        {
            string key = !string.IsNullOrEmpty(eventType) ? eventType : kind ?? "";
            key = key.Trim().ToLowerInvariant();
            return key switch
            {
                "storm" => "storm",
                "festival" => "festival",
                "price_surge" or "price" => "price",
                "announcement" => "announce",
                _ => "neutral",
            };
        }
    }
}
