using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using AgentTown.Town;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Loads <c>simulation-region-positions.json</c> — the single source for town
    /// region anchors (§6.3). Values are wire-space; convert with
    /// <see cref="WireCoordinateTransform.ToUnity(WireVec3)"/> at render time.
    ///
    /// <para>Prefer <see cref="LoadAsync"/> on all targets (WebGL cannot use <see cref="File"/>).
    /// <see cref="LoadFromFile"/> remains for EditMode / desktop convenience.</para>
    /// </summary>
    public static class RegionPositions
    {
        public const string FixtureFileName = "simulation-region-positions.json";
        public const string FixtureRelativePath = "Fixtures/" + FixtureFileName;

        public static string DefaultFixturePath =>
            Path.Combine(Application.streamingAssetsPath, "Fixtures", FixtureFileName);

        /// <summary>Parse region name → wire position from raw JSON. Returns an empty map on malformed input.</summary>
        public static Dictionary<string, WireVec3> Parse(string json)
        {
            var result = new Dictionary<string, WireVec3>();
            if (string.IsNullOrWhiteSpace(json))
            {
                return result;
            }

            JObject root;
            try
            {
                root = JObject.Parse(json);
            }
            catch (Newtonsoft.Json.JsonException)
            {
                return result;
            }

            if (root["regions"] is not JObject regions)
            {
                return result;
            }

            foreach (var pair in regions)
            {
                if (pair.Value is not JObject pos)
                {
                    continue;
                }

                result[pair.Key] = new WireVec3(
                    pos.Value<double?>("x") ?? 0.0,
                    pos.Value<double?>("y") ?? 0.0,
                    pos.Value<double?>("z") ?? 0.0);
            }

            return result;
        }

        /// <summary>
        /// StreamingAssets-safe load (WebGL + desktop). Empty map on failure.
        /// </summary>
        public static async Task<Dictionary<string, WireVec3>> LoadAsync()
        {
            string json = await StreamingAssetsText.LoadAsync(FixtureRelativePath);
            Dictionary<string, WireVec3> anchors = Parse(json);
            if (anchors.Count == 0)
            {
                Debug.LogWarning("[AgentTown] Region fixture empty or missing via StreamingAssets");
            }

            return anchors;
        }

        /// <summary>Load + parse from disk (Editor / desktop). Prefer <see cref="LoadAsync"/> on WebGL.</summary>
        public static Dictionary<string, WireVec3> LoadFromFile(string path = null)
        {
            var target = string.IsNullOrEmpty(path) ? DefaultFixturePath : path;
            if (!File.Exists(target))
            {
                Debug.LogWarning($"[AgentTown] Region fixture not found: {target}");
                return new Dictionary<string, WireVec3>();
            }

            return Parse(File.ReadAllText(target));
        }
    }
}
