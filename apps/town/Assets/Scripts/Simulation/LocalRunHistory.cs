using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using UnityEngine;

namespace AgentTown.Simulation
{
    /// <summary>
    /// One locally cached simulation run (§9 UT-10). Aligns with Desktop
    /// <c>runHistory.ts</c> semantics (recent 12, most-recent first) without sharing storage.
    /// </summary>
    public sealed class SavedRunEntry
    {
        [JsonProperty("id")] public string Id = "";
        [JsonProperty("scenario")] public string Scenario = "town";
        [JsonProperty("seed")] public int? Seed;
        [JsonProperty("createdAt")] public string CreatedAt = "";
        [JsonProperty("updatedAt")] public string UpdatedAt = "";
        [JsonProperty("lastTick")] public int? LastTick;
        [JsonProperty("status")] public string Status = "";
    }

    /// <summary>
    /// Local Run history store (§9). Prefers a JSON file under
    /// <see cref="Application.persistentDataPath"/>; falls back to <see cref="PlayerPrefs"/>
    /// (WebGL IndexedDB backend) when file IO is unavailable or fails.
    /// </summary>
    public static class LocalRunHistory
    {
        public const int MaxRuns = 12;
        public const string FileName = "simulation-run-history.json";
        /// <summary>Optional shared key with Desktop localStorage (low priority §9).</summary>
        public const string PrefsKey = "agentcore:simulation-run-history";

        /// <summary>Test seam: when set, bypasses disk / PlayerPrefs.</summary>
        internal static Func<string> ReadRawOverride;

        /// <summary>Test seam: when set, bypasses disk / PlayerPrefs.</summary>
        internal static Action<string> WriteRawOverride;

        public static string FilePath =>
            Path.Combine(Application.persistentDataPath, FileName);

        /// <summary>Most-recent first, at most <see cref="MaxRuns"/> entries.</summary>
        public static List<SavedRunEntry> List()
        {
            List<SavedRunEntry> runs = ReadAll();
            runs.Sort((a, b) =>
                string.Compare(b.UpdatedAt, a.UpdatedAt, StringComparison.Ordinal));
            if (runs.Count > MaxRuns)
            {
                runs.RemoveRange(MaxRuns, runs.Count - MaxRuns);
            }

            return runs;
        }

        /// <summary>
        /// Upsert a run to the front of the history (create / resume success). Caps at
        /// <see cref="MaxRuns"/>. Preserves the original <see cref="SavedRunEntry.CreatedAt"/>
        /// when the id already exists.
        /// </summary>
        public static void Remember(
            string id,
            string scenario = "town",
            int? seed = null,
            int? lastTick = null,
            string status = "")
        {
            if (string.IsNullOrEmpty(id))
            {
                return;
            }

            string now = DateTime.UtcNow.ToString("o");
            List<SavedRunEntry> existing = ReadAll();
            SavedRunEntry prior = existing.FirstOrDefault(r => r.Id == id);
            string createdAt = !string.IsNullOrEmpty(prior?.CreatedAt) ? prior.CreatedAt : now;

            var entry = new SavedRunEntry
            {
                Id = id,
                Scenario = string.IsNullOrEmpty(scenario) ? "town" : scenario,
                Seed = seed ?? prior?.Seed,
                CreatedAt = createdAt,
                UpdatedAt = now,
                LastTick = lastTick ?? prior?.LastTick,
                Status = status ?? prior?.Status ?? "",
            };

            List<SavedRunEntry> next = existing.Where(r => r.Id != id).ToList();
            next.Insert(0, entry);
            if (next.Count > MaxRuns)
            {
                next = next.Take(MaxRuns).ToList();
            }

            WriteAll(next);
        }

        /// <summary>Patch an existing entry (e.g. lastTick after a live advance). No-op if missing.</summary>
        public static void Update(string id, int? lastTick = null, string status = null, int? seed = null)
        {
            if (string.IsNullOrEmpty(id))
            {
                return;
            }

            List<SavedRunEntry> runs = ReadAll();
            bool changed = false;
            string now = DateTime.UtcNow.ToString("o");
            for (int i = 0; i < runs.Count; i++)
            {
                if (runs[i].Id != id)
                {
                    continue;
                }

                if (lastTick.HasValue)
                {
                    runs[i].LastTick = lastTick;
                }

                if (status != null)
                {
                    runs[i].Status = status;
                }

                if (seed.HasValue)
                {
                    runs[i].Seed = seed;
                }

                runs[i].UpdatedAt = now;
                changed = true;
                break;
            }

            if (changed)
            {
                WriteAll(runs);
            }
        }

        /// <summary>Clear history (tests / diagnostics).</summary>
        public static void Clear() => WriteAll(new List<SavedRunEntry>());

        internal static void ResetOverrides()
        {
            ReadRawOverride = null;
            WriteRawOverride = null;
        }

        private static List<SavedRunEntry> ReadAll()
        {
            string raw = ReadRaw();
            if (string.IsNullOrWhiteSpace(raw))
            {
                return new List<SavedRunEntry>();
            }

            try
            {
                List<SavedRunEntry> parsed =
                    JsonConvert.DeserializeObject<List<SavedRunEntry>>(raw, SimJson.Settings);
                if (parsed == null)
                {
                    return new List<SavedRunEntry>();
                }

                return parsed
                    .Where(r => r != null && !string.IsNullOrEmpty(r.Id))
                    .ToList();
            }
            catch (JsonException)
            {
                return new List<SavedRunEntry>();
            }
        }

        private static void WriteAll(List<SavedRunEntry> runs)
        {
            string json = JsonConvert.SerializeObject(runs ?? new List<SavedRunEntry>(), SimJson.Settings);
            WriteRaw(json);
        }

        private static string ReadRaw()
        {
            if (ReadRawOverride != null)
            {
                return ReadRawOverride() ?? "";
            }

#if UNITY_WEBGL && !UNITY_EDITOR
            return PlayerPrefs.GetString(PrefsKey, "");
#else
            try
            {
                string path = FilePath;
                if (File.Exists(path))
                {
                    return File.ReadAllText(path);
                }
            }
            catch (IOException e)
            {
                Debug.LogWarning($"[AgentTown] Run history file read failed, trying PlayerPrefs: {e.Message}");
            }
            catch (UnauthorizedAccessException e)
            {
                Debug.LogWarning($"[AgentTown] Run history file read denied, trying PlayerPrefs: {e.Message}");
            }

            return PlayerPrefs.GetString(PrefsKey, "");
#endif
        }

        private static void WriteRaw(string json)
        {
            if (WriteRawOverride != null)
            {
                WriteRawOverride(json);
                return;
            }

#if UNITY_WEBGL && !UNITY_EDITOR
            PlayerPrefs.SetString(PrefsKey, json);
            PlayerPrefs.Save();
#else
            bool fileOk = false;
            try
            {
                string path = FilePath;
                string dir = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                {
                    Directory.CreateDirectory(dir);
                }

                File.WriteAllText(path, json);
                fileOk = true;
            }
            catch (IOException e)
            {
                Debug.LogWarning($"[AgentTown] Run history file write failed, using PlayerPrefs: {e.Message}");
            }
            catch (UnauthorizedAccessException e)
            {
                Debug.LogWarning($"[AgentTown] Run history file write denied, using PlayerPrefs: {e.Message}");
            }

            // Keep PlayerPrefs in sync as a WebGL-ready / fallback mirror.
            PlayerPrefs.SetString(PrefsKey, json);
            PlayerPrefs.Save();

            if (!fileOk)
            {
                Debug.Log($"[AgentTown] Run history persisted via PlayerPrefs ({PrefsKey})");
            }
#endif
        }
    }
}
