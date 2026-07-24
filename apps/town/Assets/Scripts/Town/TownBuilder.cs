using System.Collections.Generic;
using System.Threading.Tasks;
using AgentTown.Simulation;
using Unity.AI.Navigation;
using UnityEngine;
using UnityEngine.AI;
using UnityEngine.UI;

namespace AgentTown.Town
{
    /// <summary>
    /// Runtime town builder (§7 TownScene, §15.2 step 4). Generates the whole world in code —
    /// grass base, per-region zone lots, road grid, placeholder buildings, and region anchor
    /// markers — then bakes a <see cref="NavMeshSurface"/> so NPCs can path (§7). No scene assets
    /// or <c>.uasset</c>: primitives stand in when <see cref="TownMeshCatalog"/> is empty / missing.
    ///
    /// <para>All geometry is placed via <see cref="WireCoordinateTransform"/>, so it lines up with
    /// agent positions coming from the backend. Region anchors are read from the synced fixture
    /// (§6.3) through <see cref="StreamingAssetsText"/> so it also works under WebGL.</para>
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class TownBuilder : MonoBehaviour
    {
        private const string RegionFixture = "Fixtures/" + RegionPositions.FixtureFileName;

        // Thin coloured slabs; larger Y = drawn on top (grass < zones < roads).
        private const float ZoneY = 0.03f;
        private const float RoadY = 0.07f;
        private const float SlabThickness = 0.08f;
        private const float MarkerDiscRadius = 2.2f;
        private const float MarkerDiscY = 0.16f;
        private const float RegionLabelHeight = 2.8f;

        private Material sharedMaterial;
        private Material asphaltMaterial;
        private TownMeshCatalog meshCatalog;
        private bool built;
        private bool catalogResolved;

        /// <summary>Region name → Unity anchor (transformed). Populated after <see cref="BuildAsync"/>.</summary>
        public IReadOnlyDictionary<string, Vector3> RegionAnchors => regionAnchors;

        private readonly Dictionary<string, Vector3> regionAnchors = new();

        /// <summary>Build the full town once (idempotent). Awaitable so the anchor fixture can stream on WebGL.</summary>
        public async Task BuildAsync()
        {
            if (built)
            {
                return;
            }

            built = true;
            EnsureMaterial();

            NavMeshSurface surface = BuildGroundAndNav();
            BuildGroundPatches(TownVisualLayout.Zones, "Zones", ZoneY);
            BuildGroundPatches(TownVisualLayout.Roads, "Roads", RoadY);
            BuildRoadTiles();
            await BuildRegionsAsync();
            BuildNatureProps();

            BakeNavMesh(surface);
            TownWatchPerf.SimplifySceneForWebGl(transform);
        }

        private void EnsureMaterial()
        {
            if (sharedMaterial != null)
            {
                return;
            }

            // WebGL player often strips named URP/Standard finds; keep Unlit fallbacks so boot
            // still reaches SSE (jslib) instead of ArgumentNullException on Material ctor.
            Shader shader =
                Shader.Find("Universal Render Pipeline/Lit")
                ?? Shader.Find("Universal Render Pipeline/Unlit")
                ?? Shader.Find("Standard")
                ?? Shader.Find("Unlit/Color")
                ?? Shader.Find("Sprites/Default")
                ?? Shader.Find("UI/Default");
            if (shader == null)
            {
                Debug.LogError("[AgentTown] No placeholder shader found — town materials skipped");
                return;
            }

            sharedMaterial = new Material(shader) { name = "TownPlaceholder" };
        }

        private NavMeshSurface BuildGroundAndNav()
        {
            // Soft apron under / beyond the walkable grass so bird's-eye corners
            // don't fall into the procedural skybox's dark lower hemisphere.
            var fill = GameObject.CreatePrimitive(PrimitiveType.Plane);
            fill.name = "TownHorizonFill";
            fill.transform.SetParent(transform, false);
            fill.transform.localPosition = new Vector3(0f, -0.06f, 0f);
            fill.transform.localScale = new Vector3(
                TownVisualLayout.GroundSize.x * 1.75f / 10f,
                1f,
                TownVisualLayout.GroundSize.y * 1.75f / 10f);
            StripCollider(fill);
            Paint(fill, TownPalette.HorizonFill);

            var ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            ground.name = "TownGround";
            ground.transform.SetParent(transform, false);
            // Unity Plane is 10×10 m; scale to the grass footprint.
            ground.transform.localScale = new Vector3(
                TownVisualLayout.GroundSize.x / 10f, 1f, TownVisualLayout.GroundSize.y / 10f);
            Paint(ground, TownPalette.Grass);

            // Bake only from the ground plane (Children = self + descendants), so placeholder
            // buildings — which sit outside this hierarchy — never punch holes in the nav floor.
            NavMeshSurface surface = ground.AddComponent<NavMeshSurface>();
            surface.collectObjects = CollectObjects.Children;
            surface.useGeometry = NavMeshCollectGeometry.RenderMeshes;
            return surface;
        }

        private void BakeNavMesh(NavMeshSurface surface)
        {
            if (surface == null)
            {
                return;
            }

            surface.BuildNavMesh();
            Debug.Log("[AgentTown] TownBuilder: NavMesh baked over town ground");
        }

        private void BuildGroundPatches(IReadOnlyList<GroundPatchDef> patches, string parentName, float y)
        {
            Transform parent = new GameObject(parentName).transform;
            parent.SetParent(transform, false);

            for (int i = 0; i < patches.Count; i++)
            {
                GroundPatchDef patch = patches[i];
                Vector3 center = WireCoordinateTransform.ToUnity(patch.WireX, 0.0, patch.WireZ);

                var slab = GameObject.CreatePrimitive(PrimitiveType.Cube);
                slab.name = $"{parentName}_{i}";
                slab.transform.SetParent(parent, false);
                slab.transform.position = new Vector3(center.x, y, center.z);
                slab.transform.localScale = new Vector3(
                    (float)patch.SizeX, SlabThickness, (float)patch.SizeZ);
                StripCollider(slab);
                Paint(slab, patch.Color);
            }
        }

        private async Task BuildRegionsAsync()
        {
            Dictionary<string, WireVec3> anchors = await LoadAnchorsAsync();
            regionAnchors.Clear();

            Transform buildingsParent = new GameObject("Buildings").transform;
            buildingsParent.SetParent(transform, false);
            Transform markersParent = new GameObject("Markers").transform;
            markersParent.SetParent(transform, false);

            foreach (RegionVisualDef region in TownVisualLayout.Regions)
            {
                if (!anchors.TryGetValue(region.RegionId, out WireVec3 anchor))
                {
                    Debug.LogWarning($"[AgentTown] TownBuilder: no anchor for region {region.RegionId}");
                    continue;
                }

                Vector3 anchorUnity = WireCoordinateTransform.ToUnity(anchor);
                regionAnchors[region.RegionId] = anchorUnity;

                SpawnRegionMarker(markersParent, region, anchorUnity);

                Transform regionParent = new GameObject(region.RegionId).transform;
                regionParent.SetParent(buildingsParent, false);

                for (int i = 0; i < region.Buildings.Length; i++)
                {
                    SpawnPlaceholder(
                        regionParent, region.Buildings[i], anchor, region.ZoneColor, i, region.RegionId);
                }
            }
        }

        private async Task<Dictionary<string, WireVec3>> LoadAnchorsAsync()
        {
            string json = await StreamingAssetsText.LoadAsync(RegionFixture);
            Dictionary<string, WireVec3> anchors = RegionPositions.Parse(json);
            if (anchors.Count == 0)
            {
                Debug.LogWarning("[AgentTown] TownBuilder: region fixture empty — buildings skipped");
            }

            return anchors;
        }

        /// <summary>
        /// Overlay Kenney road meshes on main arteries when the catalog has a road pool.
        /// Colour slabs always remain underneath; empty catalog → no-op (no crash).
        /// Colliders stripped so NavMesh (ground bake) stays walkable.
        /// </summary>
        private void BuildRoadTiles()
        {
            IReadOnlyList<RoadTileDef> tiles = TownVisualLayout.RoadTiles;
            if (tiles == null || tiles.Count == 0)
            {
                return;
            }

            EnsureCatalog();
            if (meshCatalog == null || !meshCatalog.HasRoads)
            {
                return;
            }

            Transform parent = new GameObject("RoadMeshes").transform;
            parent.SetParent(transform, false);

            for (int i = 0; i < tiles.Count; i++)
            {
                SpawnRoadTile(parent, tiles[i], i);
            }
        }

        /// <summary>Internal for EditMode tests.</summary>
        internal void SpawnRoadTile(Transform parent, RoadTileDef def, int index)
        {
            Vector3 basePos = WireCoordinateTransform.ToUnity(def.WireX, 0.0, def.WireZ);
            Quaternion rotation = Quaternion.Euler(0f, -def.RotationYRad * Mathf.Rad2Deg, 0f);
            float scale = Mathf.Max(0.2f, def.Scale);
            string name = $"RoadMesh_{index}";

            GameObject actor = TrySpawnRoadFromCatalog(parent, name, def.MeshName, index, basePos, rotation, scale);
            if (actor == null)
            {
                // Empty / missing stem: leave colour slab only (no primitive road mesh).
                return;
            }

            // Intentional artery scale + deck just above colour slabs (aligned to Roads[]).
            TownMeshFit.FitRoad(actor, scale);
            // Kenney road colormaps read as high-sat orange/green stripes in WebGL —
            // force a dedicated Unlit asphalt (no base map) so stripes cannot dominate.
            ApplyAsphalt(actor);
            // Sidewalk / spur tiles are decorative — cull sooner than main artery meshes.
            if (scale < 5.5f)
            {
                TownBuildingLod.Ensure(actor, 28f, 55f);
            }
            else
            {
                TownBuildingLod.Ensure(actor, 48f, 95f);
            }
        }

        private GameObject TrySpawnRoadFromCatalog(
            Transform parent,
            string name,
            string meshName,
            int index,
            Vector3 position,
            Quaternion rotation,
            float scale)
        {
            EnsureCatalog();
            if (meshCatalog == null || !meshCatalog.HasRoads)
            {
                return null;
            }

            GameObject prefab = meshCatalog.PickRoad(meshName, index);
            if (prefab == null)
            {
                return null;
            }

            try
            {
                GameObject actor = Object.Instantiate(prefab, parent);
                actor.name = name;
                actor.transform.position = position;
                actor.transform.rotation = rotation;
                // Scale applied in FitRoad after instantiate (bounds need world pose).
                actor.transform.localScale = Vector3.one;
                StripCollidersRecursive(actor);
                return actor;
            }
            catch (System.Exception ex)
            {
                Debug.LogWarning($"[AgentTown] TownBuilder: road instantiate failed ({ex.Message}) — slab fallback");
                return null;
            }
        }

        /// <summary>
        /// Spawn park / roadside foliage from <see cref="TownVisualLayout.NatureProps"/>.
        /// Catalog nature pool when present; otherwise green primitives. Never throws on empty catalog.
        /// </summary>
        private void BuildNatureProps()
        {
            IReadOnlyList<NaturePropDef> props = TownVisualLayout.NatureProps;
            if (props == null || props.Count == 0)
            {
                return;
            }

            Transform parent = new GameObject("Nature").transform;
            parent.SetParent(transform, false);

            for (int i = 0; i < props.Count; i++)
            {
                SpawnNatureProp(parent, props[i], i);
            }
        }

        /// <summary>Internal for EditMode tests.</summary>
        internal void SpawnNatureProp(Transform parent, NaturePropDef def, int index)
        {
            Vector3 basePos = WireCoordinateTransform.ToUnity(def.WireX, 0.0, def.WireZ);
            Quaternion rotation = Quaternion.Euler(0f, -def.RotationYRad * Mathf.Rad2Deg, 0f);
            float scale = Mathf.Max(0.2f, def.Scale);
            string name = $"Nature_{index}";

            GameObject actor = TrySpawnNatureFromCatalog(parent, name, def.MeshName, index, basePos, rotation);
            if (actor == null)
            {
                bool isTree = !string.IsNullOrEmpty(def.MeshName)
                    && def.MeshName.StartsWith("tree", System.StringComparison.OrdinalIgnoreCase);
                PrimitiveType primitive = isTree ? PrimitiveType.Cylinder : PrimitiveType.Cube;
                float height = isTree ? 2.4f * scale : 0.7f * scale;
                float width = isTree ? 0.55f * scale : 0.9f * scale;
                actor = GameObject.CreatePrimitive(primitive);
                actor.name = name;
                actor.transform.SetParent(parent, false);
                actor.transform.position = new Vector3(basePos.x, height * 0.5f, basePos.z);
                actor.transform.rotation = rotation;
                actor.transform.localScale = new Vector3(width, height, width);
                StripCollider(actor);
                Paint(actor, isTree
                    ? new Color(0.22f, 0.55f, 0.28f)
                    : new Color(0.30f, 0.62f, 0.32f));
            }
            else
            {
                TownMeshFit.FitNature(actor, scale, def.MeshName);
            }

            TownBuildingLod.EnsureNature(actor, def.AggressiveLod);
        }

        private GameObject TrySpawnNatureFromCatalog(
            Transform parent,
            string name,
            string meshName,
            int index,
            Vector3 position,
            Quaternion rotation)
        {
            EnsureCatalog();
            if (meshCatalog == null || !meshCatalog.HasNature)
            {
                return null;
            }

            GameObject prefab = meshCatalog.PickNature(meshName, index);
            if (prefab == null)
            {
                return null;
            }

            try
            {
                GameObject actor = Object.Instantiate(prefab, parent);
                actor.name = name;
                actor.transform.position = position;
                actor.transform.rotation = rotation;
                actor.transform.localScale = Vector3.one;
                StripCollidersRecursive(actor);
                return actor;
            }
            catch (System.Exception ex)
            {
                Debug.LogWarning($"[AgentTown] TownBuilder: nature instantiate failed ({ex.Message}) — primitive fallback");
                return null;
            }
        }

        /// <summary>
        /// Spawn one building: catalog prefab when available, else a coloured primitive.
        /// Internal for EditMode tests (empty catalog must not throw; stub catalog uses Instantiate).
        /// </summary>
        internal void SpawnPlaceholder(
            Transform parent,
            PlaceholderDef def,
            WireVec3 anchor,
            Color color,
            int index,
            string regionId = null)
        {
            // Wire-space anchor + XZ offset, then the single §6.2 transform to Unity.
            Vector3 basePos = WireCoordinateTransform.ToUnity(
                anchor.X + def.OffsetX, 0.0, anchor.Z + def.OffsetZ);

            GetShapeDimensions(def.Shape, def.Scale, out Vector3 scale, out float heightOffset, out PrimitiveType primitive);
            Quaternion rotation = Quaternion.Euler(0f, -def.RotationYRad * Mathf.Rad2Deg, 0f);
            // Catalog meshes ground at Y≈0; primitives keep centre-height offset.
            Vector3 catalogPos = new Vector3(basePos.x, TownMeshFit.GroundY, basePos.z);
            Vector3 primitivePos = new Vector3(basePos.x, heightOffset, basePos.z);
            string name = $"{parent.name}_{index}";

            GameObject actor = TrySpawnFromCatalog(
                parent, name, index, catalogPos, rotation, regionId, out string meshStem);
            if (actor == null)
            {
                actor = GameObject.CreatePrimitive(primitive);
                actor.name = name;
                actor.transform.SetParent(parent, false);
                actor.transform.position = primitivePos;
                actor.transform.rotation = rotation;
                actor.transform.localScale = scale;
                StripCollider(actor);
                Paint(actor, color);
            }
            else
            {
                TownMeshFit.FitBuilding(actor, def.Scale, meshStem);
            }
            // Catalog meshes keep imported Kenney materials (no zone-tint overwrite).
            // Distance LOD: full mesh near camera → low cube proxy → cull (watch perf).
            TownBuildingLod.Ensure(actor);
        }

        /// <summary>Inject a catalog for EditMode tests (skips Resources load).</summary>
        internal void SetMeshCatalogForTests(TownMeshCatalog catalog)
        {
            meshCatalog = catalog;
            catalogResolved = true;
        }

        private GameObject TrySpawnFromCatalog(
            Transform parent,
            string name,
            int index,
            Vector3 position,
            Quaternion rotation,
            string regionId,
            out string meshStem)
        {
            meshStem = "";
            EnsureCatalog();
            if (meshCatalog == null || !meshCatalog.HasBuildings)
            {
                return null;
            }

            // Index 0 = region landmark: prefer the bound primary mesh, then pool fill.
            GameObject prefab = index == 0 ? meshCatalog.PickPrimaryForRegion(regionId) : null;
            prefab ??= meshCatalog.PickBuilding(index);
            if (prefab == null)
            {
                return null;
            }

            meshStem = TownMeshCatalog.StripPrefabSuffixPublic(prefab.name);
            try
            {
                GameObject actor = Object.Instantiate(prefab, parent);
                actor.name = name;
                actor.transform.position = position;
                actor.transform.rotation = rotation;
                actor.transform.localScale = Vector3.one;
                StripCollidersRecursive(actor);
                return actor;
            }
            catch (System.Exception ex)
            {
                Debug.LogWarning($"[AgentTown] TownBuilder: catalog instantiate failed ({ex.Message}) — primitive fallback");
                return null;
            }
        }

        private void EnsureCatalog()
        {
            if (catalogResolved)
            {
                return;
            }

            catalogResolved = true;
            meshCatalog = TownMeshCatalog.LoadOrNull();
        }

        private void SpawnRegionMarker(Transform parent, RegionVisualDef region, Vector3 anchorUnity)
        {
            // Ground-hugging disc (was a floating sphere) — a zone-tinted floor pad that
            // anchors the label without a coloured ball hovering over the town.
            var marker = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            marker.name = $"Region_{region.RegionId}";
            marker.transform.SetParent(parent, false);
            marker.transform.position = new Vector3(anchorUnity.x, MarkerDiscY, anchorUnity.z);
            // Unity cylinder: radius 0.5, height 2 → a flat disc when the Y scale is tiny.
            marker.transform.localScale = new Vector3(MarkerDiscRadius * 2f, 0.06f, MarkerDiscRadius * 2f);
            StripCollider(marker);
            Paint(marker, region.ZoneColor);

            SpawnRegionLabel(parent, region.RegionId, anchorUnity);
        }

        /// <summary>World-space Chinese region label beside the anchor marker.</summary>
        private static void SpawnRegionLabel(Transform parent, string regionId, Vector3 anchorUnity)
        {
            var go = new GameObject($"Label_{regionId}");
            go.transform.SetParent(parent, false);
            go.transform.position = new Vector3(anchorUnity.x, RegionLabelHeight, anchorUnity.z);
            go.transform.localScale = Vector3.one * 0.04f;

            Canvas canvas = go.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = Camera.main;
            var rt = go.GetComponent<RectTransform>();
            rt.sizeDelta = new Vector2(160f, 40f);

            var textGo = new GameObject("Text");
            textGo.transform.SetParent(go.transform, false);
            Text text = textGo.AddComponent<Text>();
            text.font = TownFonts.UiFont;
            text.fontSize = 28;
            text.fontStyle = FontStyle.Bold;
            text.alignment = TextAnchor.MiddleCenter;
            text.color = Color.white;
            text.text = regionId;
            text.raycastTarget = false;
            var textRt = textGo.GetComponent<RectTransform>();
            textRt.anchorMin = Vector2.zero;
            textRt.anchorMax = Vector2.one;
            textRt.offsetMin = Vector2.zero;
            textRt.offsetMax = Vector2.zero;

            go.AddComponent<RegionLabelBillboard>();
        }

        private sealed class RegionLabelBillboard : MonoBehaviour
        {
            private void LateUpdate()
            {
                Camera cam = Camera.main;
                if (cam == null)
                {
                    return;
                }

                transform.rotation = Quaternion.LookRotation(
                    transform.position - cam.transform.position, Vector3.up);
            }
        }

        private static void GetShapeDimensions(
            PlaceholderShape shape, float scale, out Vector3 localScale, out float heightOffset, out PrimitiveType primitive)
        {
            switch (shape)
            {
                case PlaceholderShape.Disc:
                    primitive = PrimitiveType.Cylinder;
                    localScale = new Vector3(1.2f * scale, 0.15f * scale, 1.2f * scale);
                    heightOffset = 0.15f * scale;
                    break;
                case PlaceholderShape.FlatProp:
                    primitive = PrimitiveType.Cube;
                    localScale = new Vector3(3.2f * scale, 0.5f * scale, 1.4f * scale);
                    heightOffset = 0.25f * scale;
                    break;
                case PlaceholderShape.Tower:
                    primitive = PrimitiveType.Cylinder;
                    localScale = new Vector3(2.4f * scale, 3.5f * scale, 2.4f * scale);
                    heightOffset = 3.5f * scale;
                    break;
                default: // Building
                    primitive = PrimitiveType.Cube;
                    localScale = new Vector3(2.8f * scale, 3.6f * scale, 2.8f * scale);
                    heightOffset = 1.8f * scale;
                    break;
            }
        }

        private void Paint(GameObject go, Color color)
        {
            Renderer[] renderers = go.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0)
            {
                return;
            }

            var block = new MaterialPropertyBlock();
            for (int i = 0; i < renderers.Length; i++)
            {
                Renderer renderer = renderers[i];
                if (sharedMaterial != null)
                {
                    renderer.sharedMaterial = sharedMaterial;
                }

                renderer.GetPropertyBlock(block);
                block.SetColor("_BaseColor", color);
                block.SetColor("_Color", color);
                renderer.SetPropertyBlock(block);
            }
        }

        /// <summary>
        /// Replace Kenney road materials with a texture-free Unlit asphalt so WebGL
        /// never shows the imported orange/green colormap stripes.
        /// </summary>
        private void ApplyAsphalt(GameObject go)
        {
            EnsureAsphaltMaterial();
            if (asphaltMaterial == null)
            {
                Paint(go, TownPalette.Road);
                return;
            }

            Renderer[] renderers = go.GetComponentsInChildren<Renderer>(true);
            for (int i = 0; i < renderers.Length; i++)
            {
                Renderer renderer = renderers[i];
                int slotCount = Mathf.Max(1, renderer.sharedMaterials?.Length ?? 1);
                var mats = new Material[slotCount];
                for (int s = 0; s < slotCount; s++)
                {
                    Material mat = new Material(asphaltMaterial) { name = "TownAsphaltInstance" };
                    if (mat.HasProperty("_BaseMap"))
                    {
                        mat.SetTexture("_BaseMap", null);
                    }

                    if (mat.HasProperty("_MainTex"))
                    {
                        mat.SetTexture("_MainTex", null);
                    }

                    if (mat.HasProperty("_BaseColor"))
                    {
                        mat.SetColor("_BaseColor", TownPalette.Road);
                    }

                    if (mat.HasProperty("_Color"))
                    {
                        mat.SetColor("_Color", TownPalette.Road);
                    }

                    mats[s] = mat;
                }

                renderer.sharedMaterials = mats;
                renderer.SetPropertyBlock(null);
            }
        }

        private void EnsureAsphaltMaterial()
        {
            if (asphaltMaterial != null)
            {
                return;
            }

            // Prefer Unlit so lighting cannot re-tint the asphalt toward grass/orange.
            Shader shader =
                Shader.Find("Universal Render Pipeline/Unlit")
                ?? Shader.Find("Unlit/Color")
                ?? Shader.Find("Sprites/Default")
                ?? Shader.Find("Universal Render Pipeline/Lit")
                ?? Shader.Find("Standard")
                ?? Shader.Find("UI/Default");
            if (shader == null)
            {
                Debug.LogWarning("[AgentTown] No asphalt shader — falling back to Paint()");
                return;
            }

            asphaltMaterial = new Material(shader) { name = "TownAsphalt" };
            if (asphaltMaterial.HasProperty("_BaseColor"))
            {
                asphaltMaterial.SetColor("_BaseColor", TownPalette.Road);
            }

            if (asphaltMaterial.HasProperty("_Color"))
            {
                asphaltMaterial.SetColor("_Color", TownPalette.Road);
            }
        }

        /// <summary>EditMode-safe destroy: <see cref="Object.Destroy"/> is illegal outside play mode.</summary>
        private static void DestroyCompat(Object obj)
        {
            if (obj == null)
            {
                return;
            }

            if (Application.isPlaying)
            {
                Object.Destroy(obj);
            }
            else
            {
                Object.DestroyImmediate(obj);
            }
        }

        private static void StripCollider(GameObject go)
        {
            if (go.TryGetComponent(out Collider collider))
            {
                DestroyCompat(collider);
            }
        }

        private static void StripCollidersRecursive(GameObject go)
        {
            Collider[] colliders = go.GetComponentsInChildren<Collider>(true);
            for (int i = 0; i < colliders.Length; i++)
            {
                DestroyCompat(colliders[i]);
            }
        }
    }
}
