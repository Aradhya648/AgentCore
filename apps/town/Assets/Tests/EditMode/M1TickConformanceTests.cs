using System.Collections.Generic;
using System.IO;
using AgentTown.Simulation;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NUnit.Framework;
using UnityEngine;

namespace AgentTown.Tests
{
    /// <summary>
    /// EditMode conformance for <c>simulation-m1-tick.json</c> (§12): deserialize the fixture,
    /// assert projected clock / nav targets, and verify wire positions survive
    /// <see cref="WireCoordinateTransform"/> within the market oracle tolerance.
    /// </summary>
    public sealed class M1TickConformanceTests
    {
        private const float ToleranceMeters = 0.5f;
        private const string FixtureRelative = "Fixtures/simulation-m1-tick.json";

        private sealed class M1TickFixture
        {
            [JsonProperty("name")] public string Name = "";
            [JsonProperty("events")] public List<SimSseEvent> Events = new();
            [JsonProperty("projected")] public M1Projected Projected = new();
        }

        private sealed class M1Projected
        {
            [JsonProperty("run")] public M1RunClock Run = new();
            [JsonProperty("navTargets")] public Dictionary<string, WireVec3> NavTargets = new();
        }

        private sealed class M1RunClock
        {
            [JsonProperty("tick")] public int Tick;
            [JsonProperty("hour")] public int Hour;
        }

        [Test]
        public void Fixture_Deserializes_AndProjectedNavMatchesTransform()
        {
            string path = Path.Combine(Application.streamingAssetsPath, FixtureRelative);
            Assert.IsTrue(File.Exists(path), $"m1-tick fixture present at {path}");

            string json = File.ReadAllText(path);
            Assert.IsTrue(SimJson.TryDeserialize(json, out M1TickFixture fixture), "fixture deserializes");
            Assert.IsNotNull(fixture);
            Assert.AreEqual("simulation-m1-tick", fixture.Name);
            Assert.IsNotEmpty(fixture.Events, "fixture has SSE events");
            Assert.IsNotNull(fixture.Projected);
            Assert.IsNotNull(fixture.Projected.NavTargets);
            Assert.IsNotEmpty(fixture.Projected.NavTargets, "at least one projected agent");

            Assert.AreEqual(1, fixture.Projected.Run.Tick, "projected tick");
            Assert.AreEqual(9, fixture.Projected.Run.Hour, "projected hour");

            Assert.IsTrue(
                fixture.Projected.NavTargets.TryGetValue("lin", out WireVec3 linWire),
                "projected navTargets includes lin");
            Assert.AreEqual(36.0, linWire.X, 1e-6, "lin wire X (市场)");
            Assert.AreEqual(0.0, linWire.Y, 1e-6, "lin wire Y");
            Assert.AreEqual(0.0, linWire.Z, 1e-6, "lin wire Z");

            Vector3 expected = new Vector3((float)linWire.X, (float)linWire.Y, (float)(-linWire.Z));
            Vector3 unity = WireCoordinateTransform.ToUnity(linWire);
            float error = Vector3.Distance(expected, unity);
            Assert.Less(error, ToleranceMeters, "lin transform error < 0.5 m");
            Assert.AreEqual(36f, unity.x, 1e-4f, "市场 oracle X");
            Assert.AreEqual(0f, unity.y, 1e-4f, "市场 oracle Y");
            Assert.AreEqual(0f, unity.z, 1e-4f, "市场 oracle Z");
        }

        [Test]
        public void Fixture_AgentStateEvent_AppliesThroughSessionPipeline()
        {
            string path = Path.Combine(Application.streamingAssetsPath, FixtureRelative);
            Assert.IsTrue(File.Exists(path), $"m1-tick fixture present at {path}");

            JObject root = JObject.Parse(File.ReadAllText(path));
            Assert.AreEqual(1, root["projected"]?["run"]?.Value<int>("tick"));

            SimAgentState agent = null;
            if (root["events"] is JArray events)
            {
                foreach (JToken evt in events)
                {
                    if (evt?["type"]?.Value<string>() != "sim.agent_state")
                    {
                        continue;
                    }

                    if (evt["payload"]?["state"] is JObject stateObj)
                    {
                        agent = stateObj.ToObject<SimAgentState>(SimJson.Serializer);
                        break;
                    }
                }
            }

            Assert.IsNotNull(agent, "fixture contains sim.agent_state");
            Assert.AreEqual("lin", agent.AgentId);

            var session = new SimulationSession();
            session.Reset();
            var snapshot = new SimTickSnapshot
            {
                Tick = root["projected"]?["run"]?.Value<int>("tick") ?? 0,
                Hour = root["projected"]?["run"]?.Value<int>("hour") ?? 0,
            };
            snapshot.Agents[agent.AgentId] = agent;
            session.ApplySnapshot(snapshot);

            Assert.AreEqual(1, session.Tick);
            Assert.AreEqual(9, session.Hour);
            Assert.IsTrue(session.Agents.Count >= 1, "at least one agent applied");
            Assert.IsTrue(session.AgentUnityPositions.TryGetValue("lin", out Vector3 pos));
            Assert.Less(Vector3.Distance(pos, new Vector3(36f, 0f, 0f)), ToleranceMeters);
        }
    }
}
