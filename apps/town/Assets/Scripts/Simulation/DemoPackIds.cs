using System;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Offline / WebGL demo story-pack IDs. Independent of REST <c>scenario</c>
    /// (still always <c>town</c>). Default is <see cref="PriceSurge"/>.
    /// </summary>
    public static class DemoPackIds
    {
        public const string PriceSurge = "price_surge";
        public const string Festival = "festival";
        public const string TownHall = "town_hall";

        public static readonly string[] All =
        {
            PriceSurge,
            Festival,
            TownHall,
        };

        public static string Normalize(string packId)
        {
            if (string.IsNullOrWhiteSpace(packId))
            {
                return PriceSurge;
            }

            string id = packId.Trim().ToLowerInvariant();
            foreach (string known in All)
            {
                if (string.Equals(known, id, StringComparison.Ordinal))
                {
                    return known;
                }
            }

            return PriceSurge;
        }

        public static string DisplayName(string packId)
        {
            string id = Normalize(packId);
            // Prefer Offline JSON SoT when catalog is loaded.
            if (DemoStoryPackCatalog.TryGet(id, out DemoStoryPackDef def)
                && !string.IsNullOrEmpty(def.DisplayName))
            {
                return def.DisplayName;
            }

            return id switch
            {
                Festival => "节日庆典",
                TownHall => "镇政厅表决",
                _ => "涨价风波",
            };
        }

        /// <summary>Default baked frame count for a pack (pulse every 3 ticks).</summary>
        public static int DefaultFrameCount(string packId)
        {
            string id = Normalize(packId);
            if (DemoStoryPackCatalog.TryGet(id, out DemoStoryPackDef def) && def.FrameCount > 0)
            {
                return def.FrameCount;
            }

            return id switch
            {
                Festival => 18,   // 6 beats
                TownHall => 18,   // 6 beats
                _ => OfflineDemoPack.DefaultFrameCount, // 27 / 9 beats
            };
        }

        /// <summary>
        /// Landmark Offline interaction tick for headless screenshots
        /// (图书馆 / 工坊 / 图书馆 gather beats with visible overlays).
        /// </summary>
        public static int ShootLandmarkTick(string packId)
        {
            return Normalize(packId) switch
            {
                Festival => 12,  // 工坊 trade
                TownHall => 6,   // 图书馆 conversation
                _ => 9,          // price_surge 图书馆 conversation
            };
        }

        /// <summary>Wire-space region id for <see cref="ShootLandmarkTick"/> framing.</summary>
        public static string ShootLandmarkRegion(string packId)
        {
            return Normalize(packId) switch
            {
                Festival => "工坊",
                TownHall => "图书馆",
                _ => "图书馆",
            };
        }
    }
}
