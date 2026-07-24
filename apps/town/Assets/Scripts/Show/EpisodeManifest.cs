using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using AgentTown.Town;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace AgentTown.Show
{
    /// <summary>EpisodeManifest v1 — mirrors packages/contract-types EpisodeManifest.</summary>
    public sealed class EpisodeManifest
    {
        public const int ExpectedVersion = 1;
        public const string Episode3RelativePath = "Fixtures/show/episode-3-manifest.json";

        [JsonProperty("version")] public int Version = ExpectedVersion;
        [JsonProperty("season")] public string Season = "";
        [JsonProperty("episode_no")] public int EpisodeNo;
        [JsonProperty("title")] public string Title = "";
        [JsonProperty("run_id")] public string RunId = "";
        [JsonProperty("tick_range")] public EpisodeTickSpan TickRange = new();
        [JsonProperty("tagline")] public string Tagline;
        [JsonProperty("rule_line")] public string RuleLine;
        [JsonProperty("segments")] public List<EpisodeSegment> Segments = new();
        [JsonProperty("quiz")] public EpisodeQuiz Quiz;
        [JsonProperty("reveal")] public EpisodeReveal Reveal;
        [JsonProperty("highlights")] public List<EpisodeHighlight> Highlights = new();
        [JsonProperty("next_teaser")] public EpisodeNextTeaser NextTeaser = new();
    }

    public sealed class EpisodeTickSpan
    {
        [JsonProperty("start")] public int Start;
        [JsonProperty("end")] public int End;
    }

    public sealed class EpisodeShot
    {
        [JsonProperty("id")] public string Id = "";
        [JsonProperty("camera")] public string Camera = "";
        [JsonProperty("subjects")] public List<string> Subjects = new();
        [JsonProperty("tick_at")] public int TickAt;
        [JsonProperty("duration_hint_ms")] public int? DurationHintMs;
    }

    public sealed class EpisodeSegment
    {
        [JsonProperty("id")] public string Id = "";
        [JsonProperty("kind")] public string Kind = "";
        [JsonProperty("label")] public string Label;
        [JsonProperty("tick_span")] public EpisodeTickSpan TickSpan = new();
        [JsonProperty("shots")] public List<EpisodeShot> Shots = new();
        [JsonProperty("overlays")] public List<JObject> Overlays = new();
    }

    public sealed class EpisodeQuiz
    {
        [JsonProperty("focus")] public string Focus = "";
        [JsonProperty("question")] public string Question = "";
        [JsonProperty("hint")] public string Hint;
        [JsonProperty("options")] public List<string> Options = new();
        [JsonProperty("answer")] public string Answer = "";
        [JsonProperty("insert_at")] public EpisodeQuizInsert InsertAt = new();
    }

    public sealed class EpisodeQuizInsert
    {
        [JsonProperty("tick")] public int? Tick;
        [JsonProperty("after_segment_id")] public string AfterSegmentId;
        [JsonProperty("shot_id")] public string ShotId;
    }

    public sealed class EpisodeRevealStep
    {
        [JsonProperty("who")] public string Who = "";
        [JsonProperty("pick")] public string Pick = "";
        [JsonProperty("note")] public string Note;
    }

    public sealed class EpisodeReveal
    {
        [JsonProperty("intro")] public string Intro;
        [JsonProperty("steps")] public List<EpisodeRevealStep> Steps = new();
        [JsonProperty("outro")] public List<string> Outro = new();
        [JsonProperty("answer_overlay_id")] public string AnswerOverlayId;
    }

    public sealed class EpisodeHighlight
    {
        [JsonProperty("id")] public string Id = "";
        [JsonProperty("title")] public string Title = "";
        [JsonProperty("quote")] public string Quote = "";
        [JsonProperty("by")] public string By = "";
        [JsonProperty("shot_id")] public string ShotId;
        [JsonProperty("overlay_id")] public string OverlayId;
    }

    public sealed class EpisodeNextTeaser
    {
        [JsonProperty("title")] public string Title = "";
        [JsonProperty("hook")] public string Hook = "";
    }

    /// <summary>Parsed overlay with common fields flattened for playback HUD.</summary>
    public sealed class EpisodeOverlayView
    {
        public string Kind = "";
        public string Id;
        public string Text;
        public string Sub;
        public string Who;
        public string Title;
        public string Time;
        public string Mood;
        public int? TickAt;
        public string ShotId;
        public List<string> Present = new();
        public List<EpisodeRelationHint> Hints = new();
    }

    public sealed class EpisodeRelationHint
    {
        public string From = "";
        public string To = "";
        public string Kind = "";
        public string Label = "";
    }

    public static class EpisodeManifestLoader
    {
        public static EpisodeManifest Parse(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                return null;
            }

            try
            {
                return JsonConvert.DeserializeObject<EpisodeManifest>(json);
            }
            catch (JsonException e)
            {
                Debug.LogWarning($"[AgentTown] EpisodeManifest parse failed: {e.Message}");
                return null;
            }
        }

        public static bool Validate(EpisodeManifest manifest, out string error)
        {
            if (manifest == null)
            {
                error = "manifest is null";
                return false;
            }

            if (manifest.Version != EpisodeManifest.ExpectedVersion)
            {
                error = $"unsupported version {manifest.Version}";
                return false;
            }

            if (manifest.Segments == null || manifest.Segments.Count == 0)
            {
                error = "segments empty";
                return false;
            }

            if (manifest.Highlights == null || manifest.Highlights.Count == 0)
            {
                error = "highlights empty";
                return false;
            }

            error = null;
            return true;
        }

        public static async Task<EpisodeManifest> LoadEpisode3Async()
        {
            string json = await StreamingAssetsText.LoadAsync(EpisodeManifest.Episode3RelativePath);
            return Parse(json);
        }

        /// <summary>Flatten segment overlays into typed views (EditMode + playback).</summary>
        public static List<EpisodeOverlayView> FlattenOverlays(EpisodeManifest manifest)
        {
            var list = new List<EpisodeOverlayView>();
            if (manifest?.Segments == null)
            {
                return list;
            }

            foreach (EpisodeSegment segment in manifest.Segments)
            {
                if (segment?.Overlays == null)
                {
                    continue;
                }

                foreach (JObject raw in segment.Overlays)
                {
                    if (raw == null)
                    {
                        continue;
                    }

                    EpisodeOverlayView view = OverlayFromToken(raw);
                    if (view != null)
                    {
                        list.Add(view);
                    }
                }
            }

            return list;
        }

        public static EpisodeOverlayView OverlayFromToken(JObject raw)
        {
            if (raw == null)
            {
                return null;
            }

            var view = new EpisodeOverlayView
            {
                Kind = raw.Value<string>("kind") ?? "",
                Id = raw.Value<string>("id"),
                Text = raw.Value<string>("text"),
                Sub = raw.Value<string>("sub"),
                Who = raw.Value<string>("who"),
                Title = raw.Value<string>("title"),
                Time = raw.Value<string>("time"),
                Mood = raw.Value<string>("mood"),
                TickAt = raw.Value<int?>("tick_at"),
                ShotId = raw.Value<string>("shot_id"),
            };

            if (raw["present"] is JArray present)
            {
                foreach (JToken t in present)
                {
                    string id = t?.ToString();
                    if (!string.IsNullOrEmpty(id))
                    {
                        view.Present.Add(id);
                    }
                }
            }

            if (raw["hints"] is JArray hints)
            {
                foreach (JToken h in hints)
                {
                    if (h is not JObject ho)
                    {
                        continue;
                    }

                    view.Hints.Add(new EpisodeRelationHint
                    {
                        From = ho.Value<string>("from") ?? "",
                        To = ho.Value<string>("to") ?? "",
                        Kind = ho.Value<string>("kind") ?? "",
                        Label = ho.Value<string>("label") ?? "",
                    });
                }
            }

            return view;
        }

        public static EpisodeSegment SegmentAtTick(EpisodeManifest manifest, int tick)
        {
            if (manifest?.Segments == null)
            {
                return null;
            }

            foreach (EpisodeSegment segment in manifest.Segments)
            {
                if (segment?.TickSpan == null)
                {
                    continue;
                }

                if (tick >= segment.TickSpan.Start && tick <= segment.TickSpan.End)
                {
                    return segment;
                }
            }

            return null;
        }

        /// <summary>Active shot = last shot whose <c>tick_at</c> ≤ tick (within episode).</summary>
        public static EpisodeShot ShotAtTick(EpisodeManifest manifest, int tick)
        {
            EpisodeShot best = null;
            if (manifest?.Segments == null)
            {
                return null;
            }

            foreach (EpisodeSegment segment in manifest.Segments)
            {
                if (segment?.Shots == null)
                {
                    continue;
                }

                foreach (EpisodeShot shot in segment.Shots)
                {
                    if (shot == null)
                    {
                        continue;
                    }

                    if (shot.TickAt <= tick && (best == null || shot.TickAt >= best.TickAt))
                    {
                        best = shot;
                    }
                }
            }

            return best;
        }

        public static EpisodeShot FindShotById(EpisodeManifest manifest, string shotId)
        {
            if (manifest?.Segments == null || string.IsNullOrEmpty(shotId))
            {
                return null;
            }

            foreach (EpisodeSegment segment in manifest.Segments)
            {
                if (segment?.Shots == null)
                {
                    continue;
                }

                foreach (EpisodeShot shot in segment.Shots)
                {
                    if (shot != null && shot.Id == shotId)
                    {
                        return shot;
                    }
                }
            }

            return null;
        }

        public static EpisodeOverlayView FindOverlayById(EpisodeManifest manifest, string overlayId)
        {
            if (string.IsNullOrEmpty(overlayId))
            {
                return null;
            }

            foreach (EpisodeOverlayView view in FlattenOverlays(manifest))
            {
                if (view.Id == overlayId)
                {
                    return view;
                }
            }

            return null;
        }
    }
}
