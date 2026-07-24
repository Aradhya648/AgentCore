using System.Collections.Generic;
using System.IO;
using AgentTown.Simulation;
using Newtonsoft.Json;
using NUnit.Framework;
using UnityEngine;

namespace AgentTown.Tests
{
    /// <summary>
    /// ST-02 cross-platform fold reconciliation. Feeds the canonical protocol-conformance
    /// <c>sim.*</c> vectors — the single source Desktop also folds via <c>foldSimulation.ts</c> —
    /// through the real <see cref="SimulationSession"/> SSE pipeline and asserts the projected
    /// clock / nav targets / decision feed / world modifiers / active interactions equal each
    /// vector's <c>projected</c> golden. This is the Unity half of the guardrail against the two
    /// folds silently drifting.
    ///
    /// <para>Vectors are read straight from <c>packages/protocol-conformance/fixtures</c> so there
    /// is ONE source of truth (no StreamingAssets copy to fork). <c>sim.tick_frame</c> vectors
    /// reconcile via <see cref="SimulationSession.ApplySnapshot"/>, matching §6.6: Live ignores the
    /// tick_frame SSE envelope and pulls the frame via <c>GET /ticks/{n}</c> instead.</para>
    /// </summary>
    public sealed class SimulationFoldConformanceTests
    {
        private const float ToleranceMeters = 0.01f;

        /// <summary>
        /// Vectors carrying a <c>projected</c> golden. Mirrors the Desktop oracle set in
        /// <c>simConformance.test.ts</c> so both ends fold the same inputs.
        /// </summary>
        private static readonly string[] FixtureRelativePaths =
        {
            "simulation-m1-tick.json",
            "simulation/multi-agent-tick.json",
            "simulation/coordinate-transform.json",
            "simulation/interaction-conversation.json",
            "simulation/world-event.json",
            "simulation/tick-frame-snapshot.json",
        };

        // Application.dataPath = <repo>/apps/town/Assets → up three to the repo root.
        private static string FixturesRoot => Path.GetFullPath(Path.Combine(
            Application.dataPath, "..", "..", "..",
            "packages", "protocol-conformance", "fixtures"));

        public static IEnumerable<string> Fixtures => FixtureRelativePaths;

        [Test]
        [TestCaseSource(nameof(Fixtures))]
        public void Fold_MatchesGolden(string relativePath)
        {
            string path = Path.Combine(FixturesRoot, relativePath);
            Assert.IsTrue(File.Exists(path), $"canonical vector present at {path}");

            Assert.IsTrue(
                SimJson.TryDeserialize(File.ReadAllText(path), out FoldFixture fixture),
                $"{relativePath} deserializes");
            Assert.IsNotNull(fixture, $"{relativePath} fixture");
            Assert.IsNotNull(fixture.Projected, $"{relativePath} has projected golden");
            Assert.IsNotEmpty(fixture.Events, $"{relativePath} has SSE events");

            var session = new SimulationSession();
            session.Reset();
            // Empty apiBase keeps RunId set + Live mode; the tick_ended GET then degrades to a
            // harmless warning (no backend in EditMode) rather than mutating projected state.
            session.Configure("", "", "run-conformance");

            foreach (SimSseEvent evt in fixture.Events)
            {
                if (evt == null)
                {
                    continue;
                }

                if (evt.Type == "sim.tick_frame")
                {
                    SimTickSnapshot snapshot = evt.Payload?["snapshot"]?
                        .ToObject<SimTickSnapshot>(SimJson.Serializer);
                    if (snapshot != null)
                    {
                        session.ApplySnapshot(snapshot);
                    }

                    continue;
                }

                session.IngestSseEvent(evt);
            }

            FoldGolden golden = fixture.Projected;

            Assert.AreEqual(golden.Run.Tick, session.Tick, $"{relativePath} projected tick");
            Assert.AreEqual(golden.Run.Hour, session.Hour, $"{relativePath} projected hour");

            AssertNavTargets(relativePath, golden, session);
            AssertDecisions(relativePath, golden, session);
            AssertWorldModifiers(relativePath, golden, session);
            AssertActiveInteractions(relativePath, golden, session);
        }

        // navTargets: golden is Y-up wire coords; the session stores Unity coords, so transform
        // the golden through the shared WireCoordinateTransform before comparing.
        private static void AssertNavTargets(string tag, FoldGolden golden, SimulationSession session)
        {
            Assert.AreEqual(
                golden.NavTargets.Count, session.AgentUnityPositions.Count,
                $"{tag} nav target count");

            foreach (KeyValuePair<string, WireVec3> nav in golden.NavTargets)
            {
                Assert.IsTrue(
                    session.AgentUnityPositions.TryGetValue(nav.Key, out Vector3 pos),
                    $"{tag} nav target {nav.Key} present");
                Vector3 expected = WireCoordinateTransform.ToUnity(nav.Value);
                Assert.Less(
                    Vector3.Distance(pos, expected), ToleranceMeters,
                    $"{tag} nav {nav.Key} position");
            }
        }

        // decisions: newest-first, identical ordering both ends. Location/summary asserted only
        // when the golden pins them (Desktop uses a partial match).
        private static void AssertDecisions(string tag, FoldGolden golden, SimulationSession session)
        {
            Assert.AreEqual(
                golden.Decisions.Count, session.Decisions.Count,
                $"{tag} decision count");

            for (int i = 0; i < golden.Decisions.Count; i++)
            {
                GoldenDecision gd = golden.Decisions[i];
                SimDecision sd = session.Decisions[i];
                Assert.AreEqual(gd.Tick, sd.Tick, $"{tag} decision[{i}] tick");
                Assert.AreEqual(gd.AgentId, sd.AgentId, $"{tag} decision[{i}] agent");
                Assert.AreEqual(gd.ActionType, sd.ActionType, $"{tag} decision[{i}] action");
                if (gd.Location != null)
                {
                    Assert.AreEqual(gd.Location, sd.Location, $"{tag} decision[{i}] location");
                }

                if (gd.Summary != null)
                {
                    Assert.AreEqual(gd.Summary, sd.Summary, $"{tag} decision[{i}] summary");
                }
            }
        }

        private static void AssertWorldModifiers(string tag, FoldGolden golden, SimulationSession session)
        {
            if (golden.WorldModifiers == null)
            {
                return;
            }

            WorldModifiers m = session.Modifiers;
            Assert.AreEqual(
                golden.WorldModifiers.MarketPriceMultiplier, m.MarketPriceMultiplier, 1e-6,
                $"{tag} market multiplier");
            Assert.AreEqual(golden.WorldModifiers.StormActive, m.StormActive, $"{tag} storm");
            Assert.AreEqual(golden.WorldModifiers.FestivalActive, m.FestivalActive, $"{tag} festival");
            Assert.AreEqual(
                golden.WorldModifiers.SquareAttractionBoost, m.SquareAttractionBoost, 1e-6,
                $"{tag} square attraction boost");
        }

        private static void AssertActiveInteractions(string tag, FoldGolden golden, SimulationSession session)
        {
            if (golden.ActiveInteractions == null)
            {
                return;
            }

            foreach (GoldenInteraction gi in golden.ActiveInteractions)
            {
                Assert.IsTrue(
                    session.ActiveInteractions.TryGetValue(gi.Id, out ActiveInteraction ai),
                    $"{tag} active interaction {gi.Id} present");
                Assert.AreEqual(gi.Kind, ai.Kind, $"{tag} interaction {gi.Id} kind");
                Assert.AreEqual(gi.Status, ai.Status, $"{tag} interaction {gi.Id} status");
                Assert.AreEqual(gi.InitiatorId, ai.InitiatorId, $"{tag} interaction {gi.Id} initiator");
                Assert.AreEqual(gi.TargetId, ai.TargetId, $"{tag} interaction {gi.Id} target");
            }
        }

        private sealed class FoldFixture
        {
            [JsonProperty("name")] public string Name = "";
            [JsonProperty("events")] public List<SimSseEvent> Events = new();
            [JsonProperty("projected")] public FoldGolden Projected;
        }

        private sealed class FoldGolden
        {
            [JsonProperty("run")] public GoldenClock Run = new();
            [JsonProperty("navTargets")] public Dictionary<string, WireVec3> NavTargets = new();
            [JsonProperty("decisions")] public List<GoldenDecision> Decisions = new();
            [JsonProperty("worldModifiers")] public WorldModifiers WorldModifiers;
            [JsonProperty("activeInteractions")] public List<GoldenInteraction> ActiveInteractions;
        }

        private sealed class GoldenClock
        {
            [JsonProperty("tick")] public int Tick;
            [JsonProperty("hour")] public int Hour;
        }

        private sealed class GoldenDecision
        {
            [JsonProperty("tick")] public int Tick;
            [JsonProperty("agentId")] public string AgentId = "";
            [JsonProperty("actionType")] public string ActionType = "";
            [JsonProperty("location")] public string Location;
            [JsonProperty("summary")] public string Summary;
        }

        private sealed class GoldenInteraction
        {
            [JsonProperty("id")] public string Id = "";
            [JsonProperty("kind")] public string Kind = "";
            [JsonProperty("status")] public string Status = "";
            [JsonProperty("initiatorId")] public string InitiatorId = "";
            [JsonProperty("targetId")] public string TargetId;
        }
    }
}
