using AgentTown.Simulation;
using AgentTown.Town;
using NUnit.Framework;
using UnityEngine;

namespace AgentTown.Tests
{
    /// <summary>
    /// EditMode: empty catalog → primitive spawn; stub catalog → Instantiate path (no real FBX).
    /// </summary>
    public sealed class TownMeshCatalogTests
    {
        private GameObject root;

        [SetUp]
        public void SetUp()
        {
            root = new GameObject("TownMeshCatalogTests");
        }

        [TearDown]
        public void TearDown()
        {
            if (root != null)
            {
                Object.DestroyImmediate(root);
            }
        }

        [Test]
        public void SpawnPlaceholder_EmptyCatalog_DoesNotThrow_UsesPrimitive()
        {
            var builderGo = new GameObject("Builder");
            builderGo.transform.SetParent(root.transform, false);
            TownBuilder builder = builderGo.AddComponent<TownBuilder>();
            builder.SetMeshCatalogForTests(null);

            var parent = new GameObject("广场").transform;
            parent.SetParent(root.transform, false);
            var def = new PlaceholderDef(0, 0, 0f, 1f, PlaceholderShape.Building);
            var anchor = new WireVec3(0, 0, 0);

            Assert.DoesNotThrow(() =>
                builder.SpawnPlaceholder(parent, def, anchor, Color.white, 0));

            Assert.AreEqual(1, parent.childCount);
            Assert.IsNotNull(parent.GetChild(0).GetComponent<MeshFilter>());
        }

        [Test]
        public void SpawnPlaceholder_StubCatalog_InstantiatesPrefab()
        {
            var stubPrefab = GameObject.CreatePrimitive(PrimitiveType.Cube);
            stubPrefab.name = "StubBuildingPrefab";
            stubPrefab.transform.SetParent(root.transform, false);

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetBuildingPrefabs(new[] { stubPrefab });

            var builderGo = new GameObject("Builder");
            builderGo.transform.SetParent(root.transform, false);
            TownBuilder builder = builderGo.AddComponent<TownBuilder>();
            builder.SetMeshCatalogForTests(catalog);

            var parent = new GameObject("市场").transform;
            parent.SetParent(root.transform, false);
            var def = new PlaceholderDef(1, 2, 0.5f, 1.2f, PlaceholderShape.Building);
            var anchor = new WireVec3(0, 0, 0);

            builder.SpawnPlaceholder(parent, def, anchor, Color.red, 0);

            Assert.AreEqual(1, parent.childCount);
            Transform spawned = parent.GetChild(0);
            Assert.AreEqual("市场_0", spawned.name);
            // Instantiated copy keeps the stub mesh; name was overwritten by SpawnPlaceholder.
            Assert.IsNotNull(spawned.GetComponent<MeshFilter>());
            Assert.AreNotSame(stubPrefab, spawned.gameObject);

            Object.DestroyImmediate(catalog);
        }

        [Test]
        public void TownNpc_EmptyCatalog_UsesCapsule()
        {
            var npcGo = new GameObject("NPC");
            npcGo.transform.SetParent(root.transform, false);
            TownNpc npc = npcGo.AddComponent<TownNpc>();
            npc.SetMeshCatalogForTests(null);

            Assert.DoesNotThrow(() => npc.Initialize("agent-a", null));

            Transform body = npcGo.transform.Find("Body");
            Assert.IsNotNull(body);
            Assert.IsNotNull(body.GetComponent<MeshFilter>());
            Assert.IsNotNull(npcGo.GetComponent<UnityEngine.AI.NavMeshAgent>());
        }

        [Test]
        public void TownNpc_StubXbot_InstantiatesBody()
        {
            var stubXbot = GameObject.CreatePrimitive(PrimitiveType.Cube);
            stubXbot.name = "StubXbot";
            stubXbot.transform.SetParent(root.transform, false);
            stubXbot.transform.localScale = new Vector3(0.5f, 2f, 0.5f);

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetXbotPrefab(stubXbot);

            var npcGo = new GameObject("NPC");
            npcGo.transform.SetParent(root.transform, false);
            TownNpc npc = npcGo.AddComponent<TownNpc>();
            npc.SetMeshCatalogForTests(catalog);

            npc.Initialize("agent-b", null);

            Transform body = npcGo.transform.Find("Body");
            Assert.IsNotNull(body);
            Assert.AreNotSame(stubXbot, body.gameObject);
            Assert.IsNotNull(npcGo.GetComponent<UnityEngine.AI.NavMeshAgent>());

            Object.DestroyImmediate(catalog);
        }

        [Test]
        public void Catalog_PickBuilding_WrapsAndSkipsNulls()
        {
            var a = new GameObject("A");
            a.transform.SetParent(root.transform, false);
            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetBuildingPrefabs(new[] { a, null });

            Assert.AreSame(a, catalog.PickBuilding(0));
            Assert.AreSame(a, catalog.PickBuilding(1));
            Assert.AreSame(a, catalog.PickBuilding(3));
            Assert.IsTrue(catalog.HasBuildings);

            Object.DestroyImmediate(catalog);
        }

        [Test]
        public void Catalog_PickPrimaryForRegion_UsesBoundMesh()
        {
            var landmark = new GameObject("Flat");
            landmark.transform.SetParent(root.transform, false);
            var filler = new GameObject("building-a");
            filler.transform.SetParent(root.transform, false);

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetBuildingPrefabs(new[] { filler, landmark });

            Assert.AreSame(landmark, catalog.PickPrimaryForRegion("广场"));
            Assert.IsNull(catalog.PickPrimaryForRegion("不存在的区"));
            Assert.AreEqual(10, TownMeshCatalog.RegionPrimaryMeshNames.Count);
            Assert.AreEqual(10, TownMeshCatalog.RegionKenneyFallbackMeshNames.Count);

            Object.DestroyImmediate(catalog);
        }

        [Test]
        public void Catalog_PickPrimaryForRegion_FallsBackToKenneyWhenQuaterniusMissing()
        {
            var kenney = new GameObject("building-m");
            kenney.transform.SetParent(root.transform, false);
            var filler = new GameObject("building-a");
            filler.transform.SetParent(root.transform, false);

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetBuildingPrefabs(new[] { filler, kenney });

            // Quaternius "Flat" absent → Kenney fallback "building-m" for 广场.
            Assert.AreSame(kenney, catalog.PickPrimaryForRegion("广场"));

            Object.DestroyImmediate(catalog);
        }

        [Test]
        public void SpawnPlaceholder_IndexZero_PrefersRegionPrimary()
        {
            var landmark = GameObject.CreatePrimitive(PrimitiveType.Cube);
            landmark.name = "Shop";
            landmark.transform.SetParent(root.transform, false);
            var filler = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            filler.name = "building-a";
            filler.transform.SetParent(root.transform, false);

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetBuildingPrefabs(new[] { filler, landmark });

            var builderGo = new GameObject("Builder");
            builderGo.transform.SetParent(root.transform, false);
            TownBuilder builder = builderGo.AddComponent<TownBuilder>();
            builder.SetMeshCatalogForTests(catalog);

            var parent = new GameObject("市场").transform;
            parent.SetParent(root.transform, false);
            var def = new PlaceholderDef(0, 0, 0f, 1f, PlaceholderShape.Building);
            var anchor = new WireVec3(0, 0, 0);

            builder.SpawnPlaceholder(parent, def, anchor, Color.red, 0, "市场");

            Assert.AreEqual(1, parent.childCount);
            MeshFilter mf = parent.GetChild(0).GetComponent<MeshFilter>();
            Assert.IsNotNull(mf);
            Assert.IsNotNull(mf.sharedMesh);
            // Landmark is a cube primitive; filler was a sphere — vertex counts differ.
            Assert.AreEqual(landmark.GetComponent<MeshFilter>().sharedMesh.vertexCount, mf.sharedMesh.vertexCount);

            Object.DestroyImmediate(catalog);
        }

        [Test]
        public void Catalog_PickNature_PrefersStemThenWraps()
        {
            var oak = new GameObject("tree_oak");
            oak.transform.SetParent(root.transform, false);
            var bush = new GameObject("plant_bush");
            bush.transform.SetParent(root.transform, false);

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetNaturePrefabs(new[] { oak, bush });

            Assert.IsTrue(catalog.HasNature);
            Assert.AreSame(oak, catalog.PickNature("tree_oak", 0));
            Assert.AreSame(bush, catalog.PickNature("plant_bush", 1));
            Assert.AreSame(oak, catalog.PickNature("missing-stem", 0));
            Assert.AreSame(bush, catalog.PickNature(null, 1));

            Object.DestroyImmediate(catalog);
        }

        [Test]
        public void SpawnNatureProp_EmptyCatalog_DoesNotThrow_UsesPrimitive()
        {
            var builderGo = new GameObject("Builder");
            builderGo.transform.SetParent(root.transform, false);
            TownBuilder builder = builderGo.AddComponent<TownBuilder>();
            builder.SetMeshCatalogForTests(null);

            var parent = new GameObject("Nature").transform;
            parent.SetParent(root.transform, false);
            var def = new NaturePropDef(-32, 12, 0.5f, 1f, "tree_oak");

            Assert.DoesNotThrow(() => builder.SpawnNatureProp(parent, def, 0));
            Assert.AreEqual(1, parent.childCount);
            Assert.IsNotNull(parent.GetChild(0).GetComponent<TownBuildingLod>());
        }

        [Test]
        public void SpawnNatureProp_StubCatalog_InstantiatesPrefab()
        {
            var stub = GameObject.CreatePrimitive(PrimitiveType.Cube);
            stub.name = "tree_oak";
            stub.transform.SetParent(root.transform, false);

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetNaturePrefabs(new[] { stub });

            var builderGo = new GameObject("Builder");
            builderGo.transform.SetParent(root.transform, false);
            TownBuilder builder = builderGo.AddComponent<TownBuilder>();
            builder.SetMeshCatalogForTests(catalog);

            var parent = new GameObject("Nature").transform;
            parent.SetParent(root.transform, false);
            var def = new NaturePropDef(-30, 10, 0f, 1.1f, "tree_oak");

            builder.SpawnNatureProp(parent, def, 0);

            Assert.AreEqual(1, parent.childCount);
            Assert.AreEqual("Nature_0", parent.GetChild(0).name);
            Assert.AreNotSame(stub, parent.GetChild(0).gameObject);

            Object.DestroyImmediate(catalog);
        }

        [Test]
        public void SpawnPlaceholder_StubCatalog_GroundsNearZero()
        {
            var stubPrefab = GameObject.CreatePrimitive(PrimitiveType.Cube);
            stubPrefab.name = "Hospital";
            stubPrefab.transform.SetParent(root.transform, false);
            // Oversized Quaternius-like stub (cm-scale authoring).
            stubPrefab.transform.localScale = new Vector3(20f, 40f, 20f);

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetBuildingPrefabs(new[] { stubPrefab });

            var builderGo = new GameObject("Builder");
            builderGo.transform.SetParent(root.transform, false);
            TownBuilder builder = builderGo.AddComponent<TownBuilder>();
            builder.SetMeshCatalogForTests(catalog);

            var parent = new GameObject("图书馆").transform;
            parent.SetParent(root.transform, false);
            var def = new PlaceholderDef(0, 0, 0f, 1.35f, PlaceholderShape.Tower);
            var anchor = new WireVec3(-40, 0, -8);

            builder.SpawnPlaceholder(parent, def, anchor, Color.blue, 0, "图书馆");

            Assert.AreEqual(1, parent.childCount);
            Transform spawned = parent.GetChild(0);
            Renderer[] renderers = spawned.GetComponentsInChildren<Renderer>();
            Assert.Greater(renderers.Length, 0);
            Bounds b = renderers[0].bounds;
            for (int i = 1; i < renderers.Length; i++)
            {
                b.Encapsulate(renderers[i].bounds);
            }

            Assert.AreEqual(TownMeshFit.GroundY, b.min.y, 0.15f, "catalog building sits on ground");
            Assert.Less(b.size.y, 12f, "Quaternius fit clamps height");
            Assert.Greater(b.size.y, 2f);

            Object.DestroyImmediate(catalog);
        }

        [Test]
        public void Catalog_PickRoad_PrefersStemThenWraps()
        {
            var straight = new GameObject("road-straight");
            straight.transform.SetParent(root.transform, false);
            var cross = new GameObject("road-crossroad");
            cross.transform.SetParent(root.transform, false);

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetRoadPrefabs(new[] { straight, cross });

            Assert.IsTrue(catalog.HasRoads);
            Assert.AreSame(straight, catalog.PickRoad("road-straight", 0));
            Assert.AreSame(cross, catalog.PickRoad("road-crossroad", 1));
            Assert.AreSame(straight, catalog.PickRoad("missing-stem", 0));
            Assert.AreSame(cross, catalog.PickRoad(null, 1));

            Object.DestroyImmediate(catalog);
        }

        [Test]
        public void SpawnRoadTile_EmptyCatalog_DoesNotThrow_LeavesNoMesh()
        {
            var builderGo = new GameObject("Builder");
            builderGo.transform.SetParent(root.transform, false);
            TownBuilder builder = builderGo.AddComponent<TownBuilder>();
            builder.SetMeshCatalogForTests(null);

            var parent = new GameObject("RoadMeshes").transform;
            parent.SetParent(root.transform, false);
            var def = new RoadTileDef(0, 0, 0f, 7.5f, "road-straight");

            Assert.DoesNotThrow(() => builder.SpawnRoadTile(parent, def, 0));
            Assert.AreEqual(0, parent.childCount);
        }

        [Test]
        public void SpawnRoadTile_StubCatalog_InstantiatesPrefab()
        {
            var stub = GameObject.CreatePrimitive(PrimitiveType.Cube);
            stub.name = "road-straight";
            stub.transform.SetParent(root.transform, false);

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            catalog.SetRoadPrefabs(new[] { stub });

            var builderGo = new GameObject("Builder");
            builderGo.transform.SetParent(root.transform, false);
            TownBuilder builder = builderGo.AddComponent<TownBuilder>();
            builder.SetMeshCatalogForTests(catalog);

            var parent = new GameObject("RoadMeshes").transform;
            parent.SetParent(root.transform, false);
            var def = new RoadTileDef(8, 0, 0f, 7.5f, "road-straight");

            builder.SpawnRoadTile(parent, def, 0);

            Assert.AreEqual(1, parent.childCount);
            Assert.AreEqual("RoadMesh_0", parent.GetChild(0).name);
            Assert.AreNotSame(stub, parent.GetChild(0).gameObject);

            // Asphalt overwrite: Kenney colormap replaced with texture-free asphalt material.
            Renderer renderer = parent.GetChild(0).GetComponentInChildren<Renderer>();
            Assert.IsNotNull(renderer);
            Assert.IsNotNull(renderer.sharedMaterial);
            Assert.IsTrue(
                renderer.sharedMaterial.name.Contains("Asphalt"),
                "road mesh should use TownAsphalt material");

            Object.DestroyImmediate(catalog);
        }
    }
}
