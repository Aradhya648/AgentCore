using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using AgentTown.Town;
using Newtonsoft.Json;
using UnityEngine;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Offline demo story-pack catalog loaded from
    /// <c>StreamingAssets/Fixtures/demo-story-packs.json</c>
    /// (materialized from <c>packages/town-story-packs</c> via <c>pnpm gen:story-packs</c>).
    /// Mechanism fields in the JSON are ignored by Unity; backend reads the same file
    /// from packaged <c>agentcore.simulation.data</c>.
    /// </summary>
    public static class DemoStoryPackCatalog
    {
        public const string RelativePath = "Fixtures/demo-story-packs.json";
        public const string FileName = "demo-story-packs.json";

        private static readonly Dictionary<string, DemoStoryPackDef> ById =
            new Dictionary<string, DemoStoryPackDef>(StringComparer.Ordinal);

        public static bool Loaded { get; private set; }

        public static string DefaultFixturePath =>
            Path.Combine(Application.streamingAssetsPath, "Fixtures", FileName);

        /// <summary>Editor / tests: absolute path under Assets/StreamingAssets.</summary>
        public static string AssetsFixturePath =>
            Path.Combine(Application.dataPath, "StreamingAssets", "Fixtures", FileName);

        public static bool TryGet(string packId, out DemoStoryPackDef pack)
        {
            EnsureLoadedForBuild();
            return ById.TryGetValue(DemoPackIds.Normalize(packId), out pack);
        }

        public static IReadOnlyCollection<string> LoadedPackIds => ById.Keys;

        /// <summary>
        /// WebGL-safe async load via <see cref="StreamingAssetsText"/>.
        /// No-op when already populated; leaves <see cref="Loaded"/> false on failure
        /// so Offline falls back to embedded beats.
        /// </summary>
        public static async Task EnsureLoadedAsync(CancellationToken ct = default)
        {
            if (Loaded)
            {
                return;
            }

            // Prefer disk in Editor / standalone (faster, no UWR).
            if (TryLoadFromDisk())
            {
                return;
            }

            string json = await StreamingAssetsText.LoadAsync(RelativePath, ct);
            if (ct.IsCancellationRequested)
            {
                return;
            }

            if (!TryPopulate(json))
            {
                Debug.LogWarning(
                    "[AgentTown] DemoStoryPackCatalog: JSON SoT load failed — Offline will use embedded fallback beats.");
            }
        }

        /// <summary>
        /// Sync path for <see cref="OfflineDemoBuilder.Build"/> / EditMode.
        /// Tries StreamingAssets disk; does not block on network (WebGL stays unloaded → fallback).
        /// </summary>
        public static void EnsureLoadedForBuild()
        {
            if (Loaded)
            {
                return;
            }

            TryLoadFromDisk();
        }

        /// <summary>Parse + index. Returns false on empty / malformed input.</summary>
        public static bool TryPopulate(string json)
        {
            ById.Clear();
            Loaded = false;

            if (string.IsNullOrWhiteSpace(json))
            {
                return false;
            }

            DemoStoryPackFile file;
            try
            {
                file = JsonConvert.DeserializeObject<DemoStoryPackFile>(json);
            }
            catch (JsonException e)
            {
                Debug.LogWarning($"[AgentTown] DemoStoryPackCatalog: JSON parse failed: {e.Message}");
                return false;
            }

            if (file?.Packs == null || file.Packs.Count == 0)
            {
                return false;
            }

            foreach (DemoStoryPackDef pack in file.Packs)
            {
                if (pack == null || string.IsNullOrWhiteSpace(pack.Id))
                {
                    continue;
                }

                string id = DemoPackIds.Normalize(pack.Id);
                pack.Id = id;
                if (pack.Beats == null)
                {
                    pack.Beats = Array.Empty<DemoStoryBeatDef>();
                }

                ById[id] = pack;
            }

            Loaded = ById.Count > 0;
            return Loaded;
        }

        /// <summary>EditMode helper: clear cache so the next load re-reads disk/JSON.</summary>
        public static void ResetForTests()
        {
            ById.Clear();
            Loaded = false;
        }

        private static bool TryLoadFromDisk()
        {
            string path = DefaultFixturePath;
            if (!File.Exists(path))
            {
                path = AssetsFixturePath;
            }

            if (!File.Exists(path))
            {
                return false;
            }

            try
            {
                return TryPopulate(File.ReadAllText(path));
            }
            catch (IOException e)
            {
                Debug.LogWarning($"[AgentTown] DemoStoryPackCatalog: disk read failed ({path}): {e.Message}");
                return false;
            }
        }
    }

    public sealed class DemoStoryPackFile
    {
        [JsonProperty("packs")]
        public List<DemoStoryPackDef> Packs;
    }

    public sealed class DemoStoryPackDef
    {
        [JsonProperty("id")]
        public string Id;

        [JsonProperty("display_name")]
        public string DisplayName;

        [JsonProperty("frame_count")]
        public int FrameCount;

        /// <summary>2–3 sentence pack synopsis for the intro card.</summary>
        [JsonProperty("synopsis")]
        public string Synopsis;

        /// <summary>Lead cast blurbs shown on the intro card.</summary>
        [JsonProperty("cast")]
        public DemoStoryCastDef[] Cast;

        [JsonProperty("world_presets")]
        public string[] WorldPresets;

        [JsonProperty("beats")]
        public DemoStoryBeatDef[] Beats;
    }

    public sealed class DemoStoryCastDef
    {
        [JsonProperty("agent_id")]
        public string AgentId;

        [JsonProperty("name")]
        public string Name;

        [JsonProperty("blurb")]
        public string Blurb;
    }

    public sealed class DemoStoryBeatDef
    {
        [JsonProperty("kind")]
        public string Kind;

        [JsonProperty("arc_label")]
        public string ArcLabel;

        [JsonProperty("lines")]
        public DemoStoryLineDef[] Lines;

        [JsonProperty("world_blurb")]
        public string WorldBlurb;

        /// <summary>Optional inter-beat narration (shown on non-dialogue ticks / event feed).</summary>
        [JsonProperty("transition")]
        public string Transition;

        /// <summary>Optional beat-local narration (alias of transition when both present — prefer narration).</summary>
        [JsonProperty("narration")]
        public string Narration;

        [JsonProperty("vote_motion")]
        public string VoteMotion;

        /// <summary>Optional gather region (图书馆 / 工坊 / 码头…) for Offline overlay visibility.</summary>
        [JsonProperty("location")]
        public string Location;

        [JsonProperty("trade")]
        public DemoStoryTradeDef Trade;

        /// <summary>Resolved narration: <see cref="Narration"/> else <see cref="Transition"/>.</summary>
        public string ResolvedNarration =>
            !string.IsNullOrWhiteSpace(Narration) ? Narration
            : !string.IsNullOrWhiteSpace(Transition) ? Transition
            : null;
    }

    public sealed class DemoStoryLineDef
    {
        [JsonProperty("speaker")]
        public string Speaker;

        [JsonProperty("text")]
        public string Text;
    }

    public sealed class DemoStoryTradeDef
    {
        [JsonProperty("item")]
        public string Item;

        [JsonProperty("qty")]
        public int Qty;

        [JsonProperty("base_price")]
        public double BasePrice;
    }
}
