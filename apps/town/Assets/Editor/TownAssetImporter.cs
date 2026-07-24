#if UNITY_EDITOR
using System.Collections.Generic;
using System.IO;
using AgentTown.Town;
using UnityEditor;
using UnityEngine;

namespace AgentTown.Editor
{
    /// <summary>
    /// Scans <c>Assets/TownAssets</c> after sync, builds lightweight prefabs, and writes
    /// <c>Assets/Resources/Town/TownMeshCatalog.asset</c>. Menu: AgentTown → Import Town Assets.
    /// Safe when folders are empty — produces an empty catalog so runtime stays on primitives.
    /// </summary>
    public static class TownAssetImporter
    {
        private const string TownAssetsRoot = "Assets/TownAssets";
        private const string KenneyDir = TownAssetsRoot + "/Kenney";
        private const string QuaterniusDir = TownAssetsRoot + "/Quaternius";
        private const string NatureDir = TownAssetsRoot + "/Nature";
        private const string RoadsDir = TownAssetsRoot + "/Roads";
        private const string BuildingsDir = TownAssetsRoot + "/Buildings";
        private const string CharactersDir = TownAssetsRoot + "/Characters";
        private const string PrefabDir = TownAssetsRoot + "/Prefabs";
        private const string BuildingPrefabDir = PrefabDir + "/Buildings";
        private const string NaturePrefabDir = PrefabDir + "/Nature";
        private const string RoadPrefabDir = PrefabDir + "/Roads";
        private const string CharacterPrefabDir = PrefabDir + "/Characters";
        private const string ResourcesTownDir = "Assets/Resources/Town";
        private const string CatalogAssetPath = ResourcesTownDir + "/TownMeshCatalog.asset";
        private const string XbotModelPath = CharactersDir + "/Xbot.glb";

        [MenuItem("AgentTown/Import Town Assets")]
        public static void ImportFromMenu() => Import();

        /// <summary>Batch-safe entry (also called from <see cref="AgentTownProjectSetup"/>).</summary>
        public static void ImportFromBatch() => Import();

        public static void Import()
        {
            EnsureFolder(TownAssetsRoot);
            EnsureFolder(PrefabDir);
            EnsureFolder(BuildingPrefabDir);
            EnsureFolder(NaturePrefabDir);
            EnsureFolder(RoadPrefabDir);
            EnsureFolder(CharacterPrefabDir);
            EnsureFolder("Assets/Resources");
            EnsureFolder(ResourcesTownDir);

            AssetDatabase.Refresh();

            var buildingPrefabs = new List<GameObject>();
            var seenBuildingPaths = new HashSet<string>();
            // Quaternius first when present (FE-18 landmark layer); Kenney fills; curated GLBs last.
            CollectModelPrefabs(QuaterniusDir, "*.glb", BuildingPrefabDir, buildingPrefabs, seenBuildingPaths);
            CollectModelPrefabs(QuaterniusDir, "*.fbx", BuildingPrefabDir, buildingPrefabs, seenBuildingPaths);
            CollectModelPrefabs(KenneyDir, "*.fbx", BuildingPrefabDir, buildingPrefabs, seenBuildingPaths);
            CollectModelPrefabs(BuildingsDir, "*.glb", BuildingPrefabDir, buildingPrefabs, seenBuildingPaths);

            var naturePrefabs = new List<GameObject>();
            var seenNaturePaths = new HashSet<string>();
            CollectModelPrefabs(NatureDir, "*.glb", NaturePrefabDir, naturePrefabs, seenNaturePaths);
            CollectModelPrefabs(NatureDir, "*.fbx", NaturePrefabDir, naturePrefabs, seenNaturePaths);

            var roadPrefabs = new List<GameObject>();
            var seenRoadPaths = new HashSet<string>();
            CollectModelPrefabs(RoadsDir, "*.glb", RoadPrefabDir, roadPrefabs, seenRoadPaths);
            CollectModelPrefabs(RoadsDir, "*.fbx", RoadPrefabDir, roadPrefabs, seenRoadPaths);

            GameObject xbotPrefab = TryCreateCharacterPrefab(XbotModelPath, CharacterPrefabDir + "/Xbot.prefab");

            TownMeshCatalog catalog = LoadOrCreateCatalog();
            catalog.SetBuildingPrefabs(buildingPrefabs);
            catalog.SetNaturePrefabs(naturePrefabs);
            catalog.SetRoadPrefabs(roadPrefabs);
            catalog.SetXbotPrefab(xbotPrefab);
            EditorUtility.SetDirty(catalog);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();

            Debug.Log(
                $"[AgentTown] Import Town Assets: {buildingPrefabs.Count} building prefab(s), " +
                $"{naturePrefabs.Count} nature prefab(s), " +
                $"{roadPrefabs.Count} road prefab(s), " +
                $"xbot={(xbotPrefab != null ? "yes" : "no")} → {CatalogAssetPath}");
        }

        private static TownMeshCatalog LoadOrCreateCatalog()
        {
            var existing = AssetDatabase.LoadAssetAtPath<TownMeshCatalog>(CatalogAssetPath);
            if (existing != null)
            {
                return existing;
            }

            var catalog = ScriptableObject.CreateInstance<TownMeshCatalog>();
            AssetDatabase.CreateAsset(catalog, CatalogAssetPath);
            return catalog;
        }

        private static void CollectModelPrefabs(
            string modelDir,
            string searchPattern,
            string prefabDir,
            List<GameObject> into,
            HashSet<string> seenPrefabPaths)
        {
            if (!AssetDatabase.IsValidFolder(modelDir))
            {
                return;
            }

            string absDir = Path.GetFullPath(Path.Combine(Application.dataPath, "..", modelDir));
            if (!Directory.Exists(absDir))
            {
                return;
            }

            string[] files = Directory.GetFiles(absDir, searchPattern, SearchOption.TopDirectoryOnly);
            System.Array.Sort(files);

            foreach (string absFile in files)
            {
                string fileName = Path.GetFileName(absFile);
                string assetPath = $"{modelDir}/{fileName}".Replace('\\', '/');
                GameObject modelRoot = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
                if (modelRoot == null)
                {
                    Debug.LogWarning($"[AgentTown] Import: could not load model {assetPath}");
                    continue;
                }

                string prefabName = Path.GetFileNameWithoutExtension(fileName) + ".prefab";
                string prefabPath = $"{prefabDir}/{prefabName}";
                if (!seenPrefabPaths.Add(prefabPath))
                {
                    // Prefer first source (Quaternius over Kenney / Buildings when names collide).
                    continue;
                }

                GameObject prefab = CreateOrUpdatePrefab(modelRoot, prefabPath);
                if (prefab != null)
                {
                    into.Add(prefab);
                }
            }
        }

        private static GameObject TryCreateCharacterPrefab(string modelPath, string prefabPath)
        {
            GameObject modelRoot = AssetDatabase.LoadAssetAtPath<GameObject>(modelPath);
            if (modelRoot == null)
            {
                return null;
            }

            return CreateOrUpdatePrefab(modelRoot, prefabPath);
        }

        private static GameObject CreateOrUpdatePrefab(GameObject modelRoot, string prefabPath)
        {
            GameObject instance = PrefabUtility.InstantiatePrefab(modelRoot) as GameObject;
            if (instance == null)
            {
                instance = Object.Instantiate(modelRoot);
            }

            instance.name = Path.GetFileNameWithoutExtension(prefabPath);
            StripCollidersRecursive(instance);

            GameObject prefab = PrefabUtility.SaveAsPrefabAsset(instance, prefabPath);
            Object.DestroyImmediate(instance);
            return prefab;
        }

        private static void StripCollidersRecursive(GameObject root)
        {
            Collider[] colliders = root.GetComponentsInChildren<Collider>(true);
            for (int i = 0; i < colliders.Length; i++)
            {
                Object.DestroyImmediate(colliders[i]);
            }
        }

        private static void EnsureFolder(string assetPath)
        {
            if (AssetDatabase.IsValidFolder(assetPath))
            {
                return;
            }

            string parent = Path.GetDirectoryName(assetPath)?.Replace('\\', '/') ?? "Assets";
            string leaf = Path.GetFileName(assetPath);
            if (!AssetDatabase.IsValidFolder(parent))
            {
                EnsureFolder(parent);
            }

            AssetDatabase.CreateFolder(parent, leaf);
        }
    }
}
#endif
