using System.Collections.Generic;
using System.IO;
using AgentTown.Simulation;
using AgentTown.Town;
using NUnit.Framework;
using UnityEngine;

namespace AgentTown.Tests
{
    /// <summary>
    /// EditMode coverage for the local persona store (§6.4) and the resident merge that realises
    /// §4.3 step 2 (persona merge) plus §6.5 spawn offsets in the presentation layer.
    /// </summary>
    public sealed class TownPersonaTests
    {
        private static readonly string[] ExpectedAgents =
        {
            "lin", "chen", "zhao", "wang", "liu", "sun", "zhang", "yang", "wu", "xu",
        };

        [SetUp]
        public void LoadPersonas()
        {
            string path = Path.Combine(Application.streamingAssetsPath, TownPersonas.FileName);
            Assert.IsTrue(File.Exists(path), $"town-personas.json present at {path}");
            TownPersonas.Populate(File.ReadAllText(path));
        }

        [Test]
        public void Personas_LoadAllTenResidents()
        {
            Assert.AreEqual(ExpectedAgents.Length, TownPersonas.All.Count, "persona count");
            foreach (string id in ExpectedAgents)
            {
                LocalPersona persona = TownPersonas.Get(id);
                Assert.IsNotNull(persona, $"persona {id} loaded");
                Assert.IsNotEmpty(persona.Name, $"persona {id} has name");
                Assert.IsNotEmpty(persona.Bio, $"persona {id} has bio");
                Assert.IsNotEmpty(persona.Home, $"persona {id} has home");
            }
        }

        [Test]
        public void SpawnOffset_FlipsZForUnity()
        {
            // chen wire offset {x:-2, z:1.5} → Unity (x, 0, -z) per §6.2 / §6.5.
            Vector3 chen = TownPersonas.UnitySpawnOffset("chen");
            Assert.AreEqual(-2f, chen.x, 1e-4f, "offset x passes through");
            Assert.AreEqual(0f, chen.y, 1e-4f, "offset y is zero");
            Assert.AreEqual(-1.5f, chen.z, 1e-4f, "offset z flips sign");

            Vector3 lin = TownPersonas.UnitySpawnOffset("lin");
            Assert.AreEqual(Vector3.zero, lin, "zero offset stays zero");
        }

        [Test]
        public void ResidentMerge_UsesLocalPersonaAndLiveState()
        {
            var session = new SimulationSession();
            session.Reset();

            var snapshot = new SimTickSnapshot { Tick = 2, Hour = 10 };
            snapshot.Agents["lin"] = new SimAgentState
            {
                AgentId = "lin",
                Location = "市场",
                Activity = "卖面包",
                Mood = 0.4,
                Position = new WireVec3(36.0, 0.0, 0.0),
            };
            session.ApplySnapshot(snapshot);

            List<ResidentView> residents = TownResidents.Build(session);
            Assert.AreEqual(ExpectedAgents.Length, residents.Count, "roster falls back to local personas");

            ResidentView lin = residents.Find(r => r.AgentId == "lin");
            Assert.IsNotNull(lin);
            Assert.IsTrue(lin.HasLiveState, "lin has live snapshot state");
            Assert.AreEqual("市场", lin.Location, "live location wins");
            Assert.AreEqual("卖面包", lin.Activity);
            Assert.IsNotEmpty(lin.Bio, "bio falls back to local persona (§6.4)");
            // No manifest → big_five falls back to the local card (openness 0.45).
            Assert.AreEqual(0.45, lin.BigFive.Openness, 1e-4, "big_five from local fallback");

            ResidentView chen = residents.Find(r => r.AgentId == "chen");
            Assert.IsNotNull(chen);
            Assert.IsFalse(chen.HasLiveState, "chen has no live state yet");
            Assert.AreEqual("公园", chen.Location, "location falls back to home region");
        }

        [Test]
        public void ResidentMerge_PrefersLiveRelationships()
        {
            var session = new SimulationSession();
            session.Reset();

            var snapshot = new SimTickSnapshot { Tick = 9, Hour = 16 };
            snapshot.Agents["zhao"] = new SimAgentState
            {
                AgentId = "zhao",
                Location = "市场",
                Mood = -0.2,
                Relationships = new Dictionary<string, double> { ["wang"] = -0.85 },
            };
            session.ApplySnapshot(snapshot);

            ResidentView zhao = TownResidents.Merge("zhao", session);
            Assert.IsTrue(zhao.HasLiveState);
            Assert.IsTrue(zhao.Relationships.ContainsKey("wang"));
            Assert.AreEqual(-0.85, zhao.Relationships["wang"], 1e-4);
            // Local persona seed is -0.4; live snapshot must win for HUD detail.
            Assert.Less(zhao.Relationships["wang"], -0.4);
        }
    }
}
