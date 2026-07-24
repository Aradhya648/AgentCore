using System;
using System.Collections.Generic;
using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// Runtime mesh/prefab catalog for Kenney (+ optional Quaternius) buildings,
    /// curated Kenney Nature Kit foliage, Kenney City Kit (Roads) tiles, and Xbot NPC body.
    /// Loaded from <c>Resources/Town/TownMeshCatalog</c> (written by Editor Import).
    /// Empty / missing catalog → callers fall back to primitives.
    /// </summary>
    [CreateAssetMenu(fileName = "TownMeshCatalog", menuName = "AgentTown/Town Mesh Catalog")]
    public sealed class TownMeshCatalog : ScriptableObject
    {
        public const string ResourcesPath = "Town/TownMeshCatalog";

        /// <summary>
        /// Region → Quaternius landmark mesh stem (no extension). Tried first by
        /// <see cref="PickPrimaryForRegion"/>; missing assets fall through to
        /// <see cref="RegionKenneyFallbackMeshNames"/> then pool fill.
        /// Pack: OpenGameArt "LowPoly Buildings" (Quaternius, CC0).
        /// </summary>
        public static readonly IReadOnlyDictionary<string, string> RegionPrimaryMeshNames =
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["广场"] = "Flat",
                ["市场"] = "Shop",
                ["餐厅"] = "House5",
                ["面包店"] = "House4",
                ["公园"] = "House2",
                ["住宅区"] = "House",
                ["镇政厅"] = "Bank",
                ["图书馆"] = "Hospital",
                ["工坊"] = "House3",
                ["码头"] = "Flat2",
            };

        /// <summary>
        /// Kenney stems used when the Quaternius primary is absent from the catalog.
        /// </summary>
        public static readonly IReadOnlyDictionary<string, string> RegionKenneyFallbackMeshNames =
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["广场"] = "building-m",
                ["市场"] = "building-f",
                ["餐厅"] = "building-n",
                ["面包店"] = "building-g",
                ["公园"] = "low-detail-building-wide-a",
                ["住宅区"] = "building-a",
                ["镇政厅"] = "building-skyscraper-e",
                ["图书馆"] = "building-skyscraper-c",
                ["工坊"] = "building-h",
                ["码头"] = "building-d",
            };

        [SerializeField]
        private List<GameObject> buildingPrefabs = new();

        [SerializeField]
        private List<string> buildingNames = new();

        [SerializeField]
        private List<GameObject> naturePrefabs = new();

        [SerializeField]
        private List<string> natureNames = new();

        [SerializeField]
        private List<GameObject> roadPrefabs = new();

        [SerializeField]
        private List<string> roadNames = new();

        [SerializeField]
        private GameObject xbotPrefab;

        public IReadOnlyList<GameObject> BuildingPrefabs => buildingPrefabs;

        public IReadOnlyList<GameObject> NaturePrefabs => naturePrefabs;

        public IReadOnlyList<GameObject> RoadPrefabs => roadPrefabs;

        public GameObject XbotPrefab => xbotPrefab;

        public bool HasBuildings
        {
            get
            {
                if (buildingPrefabs == null || buildingPrefabs.Count == 0)
                {
                    return false;
                }

                for (int i = 0; i < buildingPrefabs.Count; i++)
                {
                    if (buildingPrefabs[i] != null)
                    {
                        return true;
                    }
                }

                return false;
            }
        }

        public bool HasNature
        {
            get
            {
                if (naturePrefabs == null || naturePrefabs.Count == 0)
                {
                    return false;
                }

                for (int i = 0; i < naturePrefabs.Count; i++)
                {
                    if (naturePrefabs[i] != null)
                    {
                        return true;
                    }
                }

                return false;
            }
        }

        public bool HasRoads
        {
            get
            {
                if (roadPrefabs == null || roadPrefabs.Count == 0)
                {
                    return false;
                }

                for (int i = 0; i < roadPrefabs.Count; i++)
                {
                    if (roadPrefabs[i] != null)
                    {
                        return true;
                    }
                }

                return false;
            }
        }

        public bool HasXbot => xbotPrefab != null;

        /// <summary>Load the Resources catalog, or null when missing / unloadable.</summary>
        public static TownMeshCatalog LoadOrNull()
        {
            try
            {
                return Resources.Load<TownMeshCatalog>(ResourcesPath);
            }
            catch (System.Exception ex)
            {
                Debug.LogWarning($"[AgentTown] TownMeshCatalog load failed: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// Primary mesh for a gameplay region: Quaternius name first, then Kenney fallback.
        /// Null when unbound or neither name is in the catalog (caller may pool-fill).
        /// </summary>
        public GameObject PickPrimaryForRegion(string regionId)
        {
            if (string.IsNullOrEmpty(regionId))
            {
                return null;
            }

            if (RegionPrimaryMeshNames.TryGetValue(regionId, out string primaryName))
            {
                GameObject primary = FindBuildingByName(primaryName);
                if (primary != null)
                {
                    return primary;
                }
            }

            if (RegionKenneyFallbackMeshNames.TryGetValue(regionId, out string fallbackName))
            {
                return FindBuildingByName(fallbackName);
            }

            return null;
        }

        /// <summary>Pick a building prefab by index (wraps). Null when the pool is empty.</summary>
        public GameObject PickBuilding(int index)
        {
            if (buildingPrefabs == null || buildingPrefabs.Count == 0)
            {
                return null;
            }

            int count = buildingPrefabs.Count;
            int start = ((index % count) + count) % count;
            for (int i = 0; i < count; i++)
            {
                GameObject candidate = buildingPrefabs[(start + i) % count];
                if (candidate != null)
                {
                    return candidate;
                }
            }

            return null;
        }

        /// <summary>Lookup by model/prefab stem (case-insensitive). Null when not found.</summary>
        public GameObject FindBuildingByName(string meshName)
        {
            return FindInPool(meshName, buildingPrefabs, buildingNames);
        }

        /// <summary>Lookup nature stem (case-insensitive). Null when not found.</summary>
        public GameObject FindNatureByName(string meshName)
        {
            return FindInPool(meshName, naturePrefabs, natureNames);
        }

        /// <summary>Lookup road stem (case-insensitive). Null when not found.</summary>
        public GameObject FindRoadByName(string meshName)
        {
            return FindInPool(meshName, roadPrefabs, roadNames);
        }

        /// <summary>
        /// Pick a nature prefab: preferred stem first, else pool wrap by index.
        /// Null when the nature pool is empty.
        /// </summary>
        public GameObject PickNature(string preferredStem, int index)
        {
            if (!string.IsNullOrEmpty(preferredStem))
            {
                GameObject preferred = FindNatureByName(preferredStem);
                if (preferred != null)
                {
                    return preferred;
                }
            }

            if (naturePrefabs == null || naturePrefabs.Count == 0)
            {
                return null;
            }

            int count = naturePrefabs.Count;
            int start = ((index % count) + count) % count;
            for (int i = 0; i < count; i++)
            {
                GameObject candidate = naturePrefabs[(start + i) % count];
                if (candidate != null)
                {
                    return candidate;
                }
            }

            return null;
        }

        /// <summary>
        /// Pick a road prefab: preferred stem first, else pool wrap by index.
        /// Null when the road pool is empty (caller keeps colour slabs).
        /// </summary>
        public GameObject PickRoad(string preferredStem, int index)
        {
            if (!string.IsNullOrEmpty(preferredStem))
            {
                GameObject preferred = FindRoadByName(preferredStem);
                if (preferred != null)
                {
                    return preferred;
                }
            }

            if (roadPrefabs == null || roadPrefabs.Count == 0)
            {
                return null;
            }

            int count = roadPrefabs.Count;
            int start = ((index % count) + count) % count;
            for (int i = 0; i < count; i++)
            {
                GameObject candidate = roadPrefabs[(start + i) % count];
                if (candidate != null)
                {
                    return candidate;
                }
            }

            return null;
        }

        /// <summary>Editor / test helper: replace the building pool (names derived from prefab names).</summary>
        public void SetBuildingPrefabs(IEnumerable<GameObject> prefabs)
        {
            SetPool(prefabs, ref buildingPrefabs, ref buildingNames);
        }

        /// <summary>Editor helper: set parallel name list (same order as prefabs).</summary>
        public void SetBuildingNames(IEnumerable<string> names)
        {
            SetNameList(names, ref buildingNames);
        }

        /// <summary>Editor / test helper: replace the nature pool.</summary>
        public void SetNaturePrefabs(IEnumerable<GameObject> prefabs)
        {
            SetPool(prefabs, ref naturePrefabs, ref natureNames);
        }

        /// <summary>Editor helper: set parallel nature name list.</summary>
        public void SetNatureNames(IEnumerable<string> names)
        {
            SetNameList(names, ref natureNames);
        }

        /// <summary>Editor / test helper: replace the road pool.</summary>
        public void SetRoadPrefabs(IEnumerable<GameObject> prefabs)
        {
            SetPool(prefabs, ref roadPrefabs, ref roadNames);
        }

        /// <summary>Editor helper: set parallel road name list.</summary>
        public void SetRoadNames(IEnumerable<string> names)
        {
            SetNameList(names, ref roadNames);
        }

        /// <summary>Editor / test helper: set the optional Xbot body prefab.</summary>
        public void SetXbotPrefab(GameObject prefab) => xbotPrefab = prefab;

        private static GameObject FindInPool(
            string meshName, List<GameObject> prefabs, List<string> names)
        {
            if (string.IsNullOrEmpty(meshName) || prefabs == null)
            {
                return null;
            }

            for (int i = 0; i < prefabs.Count; i++)
            {
                GameObject candidate = prefabs[i];
                if (candidate == null)
                {
                    continue;
                }

                string name = names != null && i < names.Count && !string.IsNullOrEmpty(names[i])
                    ? names[i]
                    : candidate.name;
                if (string.Equals(name, meshName, StringComparison.OrdinalIgnoreCase)
                    || string.Equals(StripPrefabSuffix(name), meshName, StringComparison.OrdinalIgnoreCase))
                {
                    return candidate;
                }
            }

            return null;
        }

        private static void SetPool(
            IEnumerable<GameObject> prefabs,
            ref List<GameObject> targetPrefabs,
            ref List<string> targetNames)
        {
            targetPrefabs ??= new List<GameObject>();
            targetNames ??= new List<string>();
            targetPrefabs.Clear();
            targetNames.Clear();
            if (prefabs == null)
            {
                return;
            }

            foreach (GameObject prefab in prefabs)
            {
                if (prefab != null)
                {
                    targetPrefabs.Add(prefab);
                    targetNames.Add(StripPrefabSuffix(prefab.name));
                }
            }
        }

        private static void SetNameList(IEnumerable<string> names, ref List<string> target)
        {
            target ??= new List<string>();
            target.Clear();
            if (names == null)
            {
                return;
            }

            foreach (string name in names)
            {
                target.Add(name ?? "");
            }
        }

        private static string StripPrefabSuffix(string name)
        {
            if (string.IsNullOrEmpty(name))
            {
                return "";
            }

            if (name.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
            {
                return name.Substring(0, name.Length - ".prefab".Length);
            }

            return name;
        }

        /// <summary>Public stem helper for spawn-time Quaternius / Kenney fit.</summary>
        public static string StripPrefabSuffixPublic(string name) => StripPrefabSuffix(name);
    }
}
