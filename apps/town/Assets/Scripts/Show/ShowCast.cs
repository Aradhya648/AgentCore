using System.Collections.Generic;
using UnityEngine;

namespace AgentTown.Show
{
    /// <summary>
    /// First-season dating-show cast (6 guests). Capsule + identity colour + nameplate
    /// when no catalog mesh is bound; <see cref="CatalogStem"/> reserves a future Xbot /
    /// character prefab hook without requiring assets now.
    /// </summary>
    public sealed class ShowCastMember
    {
        public string Id;
        public string Name;
        public string Role;
        public Color Color;
        /// <summary>Optional TownMeshCatalog / character stem; empty → capsule fallback.</summary>
        public string CatalogStem;
    }

    public static class ShowCast
    {
        public static readonly ShowCastMember[] Members =
        {
            new()
            {
                Id = "shenwan", Name = "沈晚", Role = "设计师",
                Color = new Color(0.92f, 0.42f, 0.55f), CatalogStem = "",
            },
            new()
            {
                Id = "luye", Name = "陆野", Role = "创业者",
                Color = new Color(0.28f, 0.55f, 0.95f), CatalogStem = "",
            },
            new()
            {
                Id = "xuanan", Name = "许安安", Role = "编辑",
                Color = new Color(0.95f, 0.72f, 0.35f), CatalogStem = "",
            },
            new()
            {
                Id = "jiangyu", Name = "蒋予", Role = "自由职业",
                Color = new Color(0.55f, 0.85f, 0.35f), CatalogStem = "",
            },
            new()
            {
                Id = "zhouke", Name = "周可", Role = "咨询顾问",
                Color = new Color(0.55f, 0.45f, 0.90f), CatalogStem = "",
            },
            new()
            {
                Id = "xieheng", Name = "谢衡", Role = "工程师",
                Color = new Color(0.35f, 0.78f, 0.82f), CatalogStem = "",
            },
        };

        private static readonly Dictionary<string, ShowCastMember> ById = BuildIndex();

        private static Dictionary<string, ShowCastMember> BuildIndex()
        {
            var map = new Dictionary<string, ShowCastMember>();
            foreach (ShowCastMember m in Members)
            {
                map[m.Id] = m;
            }

            return map;
        }

        public static bool TryGet(string id, out ShowCastMember member) =>
            ById.TryGetValue(id ?? "", out member);

        public static string DisplayName(string id) =>
            TryGet(id, out ShowCastMember m) ? m.Name : (id ?? "");

        public static bool TryGetColor(string id, out Color color)
        {
            if (TryGet(id, out ShowCastMember m))
            {
                color = m.Color;
                return true;
            }

            color = default;
            return false;
        }
    }
}
