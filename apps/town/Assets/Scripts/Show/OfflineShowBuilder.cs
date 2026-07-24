using System;
using System.Collections.Generic;
using AgentTown.Simulation;
using AgentTown.Town;
using UnityEngine;

namespace AgentTown.Show
{
    /// <summary>
    /// Synthesise offline tick frames from an <see cref="EpisodeManifest"/> so programme
    /// mode still goes through <see cref="SimulationSession.ApplySnapshot"/> only.
    /// Agent poses are derived from segment kind + scene overlays + shot subjects
    /// (manifest does not embed world motion — same contract as TS EpisodeManifest).
    /// </summary>
    public static class OfflineShowBuilder
    {
        public const string HeartCampRegion = "心动营地";
        public const string MarketRegion = "市场";
        public const string DockRegion = "码头";
        public const string SquareRegion = "广场";
        public const string HomesRegion = "住宅区";

        public static OfflineDemoPack Build(
            EpisodeManifest manifest,
            IReadOnlyDictionary<string, WireVec3> regions)
        {
            if (manifest == null)
            {
                throw new ArgumentNullException(nameof(manifest));
            }

            Dictionary<string, WireVec3> anchors = ResolveAnchors(regions);
            List<EpisodeOverlayView> overlays = EpisodeManifestLoader.FlattenOverlays(manifest);

            int start = manifest.TickRange?.Start ?? 0;
            int end = manifest.TickRange?.End ?? start;
            if (end < start)
            {
                end = start;
            }

            var pack = new OfflineDemoPack
            {
                RunId = string.IsNullOrEmpty(manifest.RunId) ? "show-episode" : manifest.RunId,
                PackId = DemoPackIds.PriceSurge,
                Manifest = new RunManifest
                {
                    ManifestVersion = $"show-episode:{manifest.EpisodeNo}",
                    Scenario = "show",
                    Seed = 3,
                    Personas = new List<SimPersona>(),
                    Regions = new List<string>(anchors.Keys),
                },
                Frames = new List<SimTickSnapshot>(),
                Decisions = new List<SimDecision>(),
                Events = new List<SimTickEvent>(),
                Interactions = new List<ActiveInteraction>(),
            };

            foreach (ShowCastMember member in ShowCast.Members)
            {
                pack.Manifest.Personas.Add(new SimPersona
                {
                    AgentId = member.Id,
                    Name = member.Name,
                    Role = member.Role,
                    Location = HeartCampRegion,
                    Goal = "",
                });
            }

            for (int tick = start; tick <= end; tick++)
            {
                EpisodeSegment segment = EpisodeManifestLoader.SegmentAtTick(manifest, tick);
                EpisodeShot shot = EpisodeManifestLoader.ShotAtTick(manifest, tick);
                EpisodeOverlayView scene = LatestScene(overlays, tick);
                string region = ResolveRegion(segment, scene, shot);
                int hour = HourFor(segment, scene);

                var snapshot = new SimTickSnapshot
                {
                    Tick = tick,
                    Hour = hour,
                    Agents = new Dictionary<string, SimAgentState>(),
                    Modifiers = new WorldModifiers(),
                    ActiveEvents = new List<WorldEvent>(),
                    Metrics = null,
                };

                HashSet<string> present = ResolvePresent(scene, shot, segment);
                PlaceCast(snapshot, present, region, anchors, tick, shot);

                pack.Frames.Add(snapshot);
            }

            return pack;
        }

        private static Dictionary<string, WireVec3> ResolveAnchors(
            IReadOnlyDictionary<string, WireVec3> regions)
        {
            var anchors = new Dictionary<string, WireVec3>();
            if (regions != null)
            {
                foreach (KeyValuePair<string, WireVec3> pair in regions)
                {
                    anchors[pair.Key] = pair.Value;
                }
            }

            if (!anchors.ContainsKey(HeartCampRegion))
            {
                anchors[HeartCampRegion] = new WireVec3(-56, 0, 36);
            }

            if (!anchors.ContainsKey(MarketRegion))
            {
                anchors[MarketRegion] = new WireVec3(36, 0, 0);
            }

            if (!anchors.ContainsKey(DockRegion))
            {
                anchors[DockRegion] = new WireVec3(-8, 0, 40);
            }

            if (!anchors.ContainsKey(SquareRegion))
            {
                anchors[SquareRegion] = new WireVec3(0, 0, 0);
            }

            if (!anchors.ContainsKey(HomesRegion))
            {
                anchors[HomesRegion] = new WireVec3(18, 0, 38);
            }

            return anchors;
        }

        private static EpisodeOverlayView LatestScene(List<EpisodeOverlayView> overlays, int tick)
        {
            EpisodeOverlayView best = null;
            foreach (EpisodeOverlayView view in overlays)
            {
                if (view == null || view.Kind != "scene" || !view.TickAt.HasValue)
                {
                    continue;
                }

                if (view.TickAt.Value <= tick
                    && (best == null || view.TickAt.Value >= best.TickAt.Value))
                {
                    best = view;
                }
            }

            return best;
        }

        private static string ResolveRegion(
            EpisodeSegment segment, EpisodeOverlayView scene, EpisodeShot shot)
        {
            string kind = segment?.Kind ?? "";
            string mood = scene?.Mood ?? "";
            string title = scene?.Title ?? "";

            if (title.Contains("湖") || (shot != null && shot.Id != null && shot.Id.Contains("lake")))
            {
                return DockRegion;
            }

            if (title.Contains("市集") || title.Contains("市场") || kind == "day")
            {
                return MarketRegion;
            }

            if (title.Contains("房间") || kind == "ceremony")
            {
                return HomesRegion;
            }

            if (kind == "night" || kind == "reveal" || kind == "quiz"
                || kind == "epilogue" || mood == "fire" || mood == "night"
                || title.Contains("篝火") || title.Contains("营地") || title.Contains("公示"))
            {
                return HeartCampRegion;
            }

            if (kind == "recap")
            {
                return SquareRegion;
            }

            return HeartCampRegion;
        }

        private static int HourFor(EpisodeSegment segment, EpisodeOverlayView scene)
        {
            string mood = scene?.Mood ?? "";
            string kind = segment?.Kind ?? "";
            if (mood == "fire" || mood == "night" || kind == "night" || kind == "reveal"
                || kind == "ceremony" || kind == "epilogue" || kind == "quiz")
            {
                return 21;
            }

            if (kind == "day")
            {
                return 10;
            }

            return 18;
        }

        private static HashSet<string> ResolvePresent(
            EpisodeOverlayView scene, EpisodeShot shot, EpisodeSegment segment)
        {
            var present = new HashSet<string>(StringComparer.Ordinal);
            if (scene?.Present != null && scene.Present.Count > 0)
            {
                foreach (string id in scene.Present)
                {
                    if (!string.IsNullOrEmpty(id))
                    {
                        present.Add(id);
                    }
                }
            }
            else if (shot?.Subjects != null && shot.Subjects.Count > 0)
            {
                foreach (string id in shot.Subjects)
                {
                    if (!string.IsNullOrEmpty(id))
                    {
                        present.Add(id);
                    }
                }
            }
            else if (segment?.Kind == "day" || segment?.Kind == "night"
                     || segment?.Kind == "reveal" || segment?.Kind == "recap")
            {
                foreach (ShowCastMember m in ShowCast.Members)
                {
                    present.Add(m.Id);
                }
            }

            return present;
        }

        private static void PlaceCast(
            SimTickSnapshot snapshot,
            HashSet<string> present,
            string region,
            Dictionary<string, WireVec3> anchors,
            int tick,
            EpisodeShot shot)
        {
            if (!anchors.TryGetValue(region, out WireVec3 regionWire))
            {
                regionWire = anchors[HeartCampRegion];
                region = HeartCampRegion;
            }

            bool ring = region == HeartCampRegion;
            int presentIndex = 0;
            int presentCount = Math.Max(1, present.Count);

            for (int i = 0; i < ShowCast.Members.Length; i++)
            {
                ShowCastMember member = ShowCast.Members[i];
                bool isPresent = present.Count == 0 || present.Contains(member.Id);
                string loc = isPresent ? region : HomesRegion;
                if (!anchors.TryGetValue(loc, out WireVec3 baseWire))
                {
                    baseWire = regionWire;
                    loc = region;
                }

                WireVec3 pos;
                if (isPresent && ring)
                {
                    float angle = (presentIndex / (float)presentCount) * Mathf.PI * 2f
                                  + tick * 0.01f;
                    float radius = 4.2f;
                    pos = new WireVec3(
                        baseWire.X + Math.Cos(angle) * radius,
                        0,
                        baseWire.Z + Math.Sin(angle) * radius);
                    presentIndex++;
                }
                else if (isPresent && shot?.Subjects != null && shot.Subjects.Count >= 2
                         && shot.Subjects.Contains(member.Id))
                {
                    int subIdx = shot.Subjects.IndexOf(member.Id);
                    double ox = (subIdx - (shot.Subjects.Count - 1) * 0.5) * 2.2;
                    pos = new WireVec3(baseWire.X + ox, 0, baseWire.Z + (i % 2) * 1.2);
                    presentIndex++;
                }
                else if (isPresent)
                {
                    double ox = ((presentIndex % 3) - 1) * 2.4;
                    double oz = (presentIndex / 3) * 2.2;
                    pos = new WireVec3(baseWire.X + ox, 0, baseWire.Z + oz);
                    presentIndex++;
                }
                else
                {
                    // Standby near homes — not on stage.
                    double ox = (i % 3) * 2.0 - 2.0;
                    double oz = (i / 3) * 2.0;
                    pos = new WireVec3(baseWire.X + ox, 0, baseWire.Z + oz);
                }

                snapshot.Agents[member.Id] = new SimAgentState
                {
                    AgentId = member.Id,
                    Name = member.Name,
                    Role = member.Role,
                    Location = loc,
                    Position = pos,
                    Activity = isPresent ? "出场" : "待机",
                    Mood = 0.2,
                    Goal = "",
                    LastThought = "",
                    Money = 100,
                    Relationships = new Dictionary<string, double>(),
                };
            }
        }
    }
}
