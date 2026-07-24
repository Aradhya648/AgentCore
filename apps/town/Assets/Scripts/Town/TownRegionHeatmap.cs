using System.Collections.Generic;
using AgentTown.Simulation;
using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// Semi-transparent mood/density overlays on region ground lots — port of Desktop
    /// <c>TownRegionHeatmap</c> / <c>regionStats.ts</c>.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class TownRegionHeatmap : MonoBehaviour
    {
        private const float HeatY = 0.05f;

        private SimulationSession session;
        private Material sharedMaterial;
        private readonly Dictionary<string, Renderer> overlays = new();
        private readonly List<string> regionIds = new();
        private readonly HashSet<string> eventHighlightIds = new();
        private float eventHighlightBoost;

        public void Bind(SimulationSession target)
        {
            Unsubscribe();
            session = target;
            EnsureOverlays();
            Subscribe();
            Refresh();
        }

        private void OnEnable()
        {
            session ??= SimulationSession.Instance;
            EnsureOverlays();
            Subscribe();
            Refresh();
        }

        private void OnDisable() => Unsubscribe();

        private void Subscribe()
        {
            if (session != null)
            {
                session.OnSnapshotApplied += Refresh;
            }
        }

        private void Unsubscribe()
        {
            if (session != null)
            {
                session.OnSnapshotApplied -= Refresh;
            }
        }

        private void EnsureOverlays()
        {
            if (overlays.Count > 0)
            {
                return;
            }

            EnsureMaterial();
            regionIds.Clear();
            Transform parent = new GameObject("RegionHeatmap").transform;
            parent.SetParent(transform, false);

            IReadOnlyList<RegionVisualDef> regions = TownVisualLayout.Regions;
            IReadOnlyList<GroundPatchDef> zones = TownVisualLayout.Zones;
            int count = Mathf.Min(regions.Count, zones.Count);

            for (int i = 0; i < count; i++)
            {
                RegionVisualDef region = regions[i];
                GroundPatchDef zone = zones[i];
                regionIds.Add(region.RegionId);

                Vector3 center = WireCoordinateTransform.ToUnity(zone.WireX, 0.0, zone.WireZ);
                var slab = GameObject.CreatePrimitive(PrimitiveType.Cube);
                slab.name = $"Heat_{region.RegionId}";
                slab.transform.SetParent(parent, false);
                slab.transform.position = new Vector3(center.x, HeatY, center.z);
                // WebGL: slightly smaller slabs cut transparent overdraw while keeping a readable tint.
                float footprint =
#if UNITY_WEBGL && !UNITY_EDITOR
                    0.88f;
#else
                    0.92f;
#endif
                slab.transform.localScale = new Vector3(
                    (float)zone.SizeX * footprint, 0.04f, (float)zone.SizeZ * footprint);

                if (slab.TryGetComponent(out Collider col))
                {
                    if (Application.isPlaying) Object.Destroy(col);
                    else Object.DestroyImmediate(col);
                }

                Renderer renderer = slab.GetComponent<Renderer>();
                if (sharedMaterial != null)
                {
                    renderer.sharedMaterial = sharedMaterial;
                }

                SetColor(renderer, new Color(1f, 1f, 1f, 0.04f));
                overlays[region.RegionId] = renderer;
            }
        }

        /// <summary>
        /// Soft-tint regions related to active world events (festival/storm/price…).
        /// Empty clears the boost; mood heatmap still drives base colour.
        /// </summary>
        public void SetEventHighlights(IReadOnlyList<string> regionIdsToHighlight, float boost = 0.22f)
        {
            eventHighlightIds.Clear();
            eventHighlightBoost = Mathf.Clamp01(boost);
            if (regionIdsToHighlight != null)
            {
                for (int i = 0; i < regionIdsToHighlight.Count; i++)
                {
                    string id = regionIdsToHighlight[i];
                    if (!string.IsNullOrEmpty(id))
                    {
                        eventHighlightIds.Add(id);
                    }
                }
            }

            Refresh();
        }

        public void ClearEventHighlights() => SetEventHighlights(null, 0f);

        private void Refresh()
        {
            if (session == null || overlays.Count == 0)
            {
                return;
            }

            List<RegionStat> stats = RegionStats.Compute(session.Agents, regionIds);
            var byId = new Dictionary<string, RegionStat>();
            for (int i = 0; i < stats.Count; i++)
            {
                byId[stats[i].Id] = stats[i];
            }

            foreach (KeyValuePair<string, Renderer> pair in overlays)
            {
                Color color;
                if (!byId.TryGetValue(pair.Key, out RegionStat stat) || stat.Population <= 0)
                {
                    color = new Color(1f, 1f, 1f, 0.03f);
                }
                else
                {
                    color = RegionStats.MoodHeatmapColor(stat.AvgMood, stat.PopulationRatio);
                }

                if (eventHighlightIds.Contains(pair.Key) && eventHighlightBoost > 0.001f)
                {
                    color = ApplyEventBoost(color, pair.Key, eventHighlightBoost);
                }

#if UNITY_WEBGL && !UNITY_EDITOR
                // Low-cost heat — readable mood tint without a translucent wall.
                color.a = Mathf.Min(color.a, 0.12f);
#endif
                SetColor(pair.Value, color);
            }
        }

        private static Color ApplyEventBoost(Color baseColor, string regionId, float boost)
        {
            Color accent = regionId switch
            {
                "广场" or "公园" => new Color(0.95f, 0.55f, 0.75f, 1f),
                "市场" or "面包店" => new Color(0.95f, 0.72f, 0.25f, 1f),
                "住宅区" => new Color(0.45f, 0.55f, 0.85f, 1f),
                "镇政厅" => new Color(0.4f, 0.65f, 0.9f, 1f),
                _ => new Color(0.7f, 0.75f, 0.95f, 1f),
            };
            Color mixed = Color.Lerp(baseColor, accent, boost);
            mixed.a = Mathf.Clamp01(Mathf.Max(baseColor.a, 0.1f) + boost * 0.35f);
            return mixed;
        }

        private void EnsureMaterial()
        {
            if (sharedMaterial != null)
            {
                return;
            }

            // Editor-authored transparent URP Unlit (AgentTownProjectSetup.EnsureRegionHeatMaterial):
            // blend state + _SURFACE_TYPE_TRANSPARENT are serialized, so the variant ships in
            // players. Runtime `_Surface=1` alone leaves the opaque blend state → the old
            // solid "green wall" slabs on WebGL.
            sharedMaterial = Resources.Load<Material>("Town/Materials/RegionHeatOverlay");
            if (sharedMaterial != null)
            {
                return;
            }

            Debug.LogWarning("[AgentTown] RegionHeatOverlay.mat missing — building runtime fallback");
            Shader shader =
                Shader.Find("Universal Render Pipeline/Unlit")
                ?? Shader.Find("Unlit/Color")
                ?? Shader.Find("Sprites/Default")
                ?? Shader.Find("UI/Default")
                ?? Shader.Find("Standard");
            if (shader == null)
            {
                return;
            }

            sharedMaterial = new Material(shader) { name = "RegionHeatmap" };
            if (sharedMaterial.HasProperty("_Surface"))
            {
                sharedMaterial.SetFloat("_Surface", 1f); // Transparent
                sharedMaterial.SetFloat("_Blend", 0f);   // Alpha
                sharedMaterial.SetFloat(
                    "_SrcBlend", (float)UnityEngine.Rendering.BlendMode.SrcAlpha);
                sharedMaterial.SetFloat(
                    "_DstBlend", (float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
                sharedMaterial.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
                sharedMaterial.SetOverrideTag("RenderType", "Transparent");
            }

            sharedMaterial.SetFloat("_ZWrite", 0f);
            sharedMaterial.renderQueue = 3000;
        }

        private static void SetColor(Renderer renderer, Color color)
        {
            if (renderer == null)
            {
                return;
            }

            var block = new MaterialPropertyBlock();
            renderer.GetPropertyBlock(block);
            block.SetColor("_BaseColor", color);
            block.SetColor("_Color", color);
            renderer.SetPropertyBlock(block);
        }
    }
}
