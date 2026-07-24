using System.Collections.Generic;
using AgentTown.Simulation;
using AgentTown.Town;
using NUnit.Framework;
using UnityEngine;

namespace AgentTown.Tests
{
    /// <summary>
    /// EditMode checks for the engine-agnostic session pipeline (§4.3). Mirrors the retired
    /// UE ApplySnapshot test: an agent at wire 市场 <c>(36,0,0)</c> lands at Unity
    /// <c>(36,0,0)</c>, and cached frames are addressable for replay.
    /// </summary>
    public sealed class SimulationSessionTests
    {
        [Test]
        public void ApplySnapshot_TransformsAgentPositions()
        {
            var session = new SimulationSession();
            session.Reset();

            var snapshot = new SimTickSnapshot
            {
                Tick = 1,
                Hour = 9,
            };
            snapshot.Agents["agent-1"] = new SimAgentState
            {
                AgentId = "agent-1",
                Name = "林小梅",
                Location = "市场",
                Position = new WireVec3(36.0, 0.0, 0.0),
            };

            session.ApplySnapshot(snapshot);

            Assert.AreEqual(1, session.Tick);
            Assert.AreEqual(9, session.Hour);
            Assert.IsTrue(session.AgentUnityPositions.ContainsKey("agent-1"));

            Vector3 pos = session.AgentUnityPositions["agent-1"];
            Assert.AreEqual(36f, pos.x, 1e-4f, "agent X");
            Assert.AreEqual(0f, pos.y, 1e-4f, "agent Y");
            Assert.AreEqual(0f, pos.z, 1e-4f, "agent Z");
        }

        [Test]
        public void ApplySnapshot_CachesFrameForReplay()
        {
            var session = new SimulationSession();
            session.Reset();

            var snapshot = new SimTickSnapshot { Tick = 3, Hour = 11 };
            session.ApplySnapshot(snapshot);

            Assert.IsTrue(session.TickCache.ContainsKey(3), "tick 3 cached");
            Assert.AreEqual(3, session.DisplayTick);
        }

        [Test]
        public void OfflineDemo_SeekAcrossFrames_DoesNotThrow()
        {
            var session = new SimulationSession();
            session.Reset();

            var personas = new List<LocalPersona>
            {
                new LocalPersona
                {
                    AgentId = "lin",
                    Name = "林小梅",
                    Role = "面包师",
                    Home = "面包店",
                    SpawnOffset = new PersonaOffset(),
                },
                new LocalPersona
                {
                    AgentId = "chen",
                    Name = "陈大爷",
                    Role = "退休教师",
                    Home = "公园",
                    SpawnOffset = new PersonaOffset { X = -2, Z = 1.5 },
                },
            };
            var regions = new Dictionary<string, WireVec3>
            {
                ["广场"] = new WireVec3(0, 0, 0),
                ["市场"] = new WireVec3(36, 0, 0),
                ["面包店"] = new WireVec3(36, 0, -22),
                ["公园"] = new WireVec3(-18, 0, 6),
                ["餐厅"] = new WireVec3(36, 0, 12),
                ["住宅区"] = new WireVec3(12, 0, 24),
                ["镇政厅"] = new WireVec3(-12, 0, -10),
            };

            OfflineDemoPack pack = OfflineDemoBuilder.Build(personas, regions, frameCount: 12);
            Assert.GreaterOrEqual(pack.Frames.Count, 8, "at least 8 demo frames");
            // Pulse every 3 ticks over 12 frames → 4 story interactions (vote is beat 6 @18).
            Assert.GreaterOrEqual(pack.Interactions.Count, 4, "demo pulse cadence denser than one-offs");
            Assert.IsNotNull(pack.Frames[0].Metrics, "demo frames carry metrics");
            Assert.IsNotNull(pack.Frames[4].Modifiers, "demo frames carry modifiers");

            session.EnterOfflineDemo(pack);
            Assert.IsTrue(session.IsOffline);
            Assert.AreEqual(OfflineDemoPack.DemoRunId, session.RunId);
            Assert.AreEqual(1, session.Playhead);
            Assert.AreEqual(12, session.Tick, "tail preserved");
            Assert.GreaterOrEqual(session.Decisions.Count, 1);
            Assert.GreaterOrEqual(session.TickEvents.Count, 1);

            Assert.DoesNotThrow(() => session.SeekTick(3));
            Assert.AreEqual(3, session.Playhead);
            Assert.GreaterOrEqual(session.ActiveInteractions.Count, 1, "conversation cue at tick 3");

            Assert.DoesNotThrow(() => session.SeekTick(5));
            Assert.AreEqual(5, session.Playhead);
            Assert.AreEqual(12, session.Tick, "tail still preserved after seek");
            Assert.AreEqual(5, session.DisplayTick);
            Assert.IsTrue(session.Agents.Count >= 2);
            // price_surge pack: market surge window is ticks 3–9 (festival starts @18).
            Assert.Greater(session.Modifiers.MarketPriceMultiplier, 1.01, "price surge window in early demo");
            Assert.IsNotNull(session.Metrics);

            Assert.DoesNotThrow(() => session.SeekTick(12));
            Assert.AreEqual(12, session.Playhead);
            Assert.IsTrue(session.Modifiers.StormActive, "storm window @ tick 12");
            Assert.AreEqual((8 + 12 - 1) % 24, session.Hour, "hour follows demo clock");

            Assert.DoesNotThrow(() => session.StepPlaybackTick(-1));
            Assert.AreEqual(11, session.Playhead);

            session.SetPlaying(true);
            Assert.DoesNotThrow(() => session.UpdatePlayback(10f));
            Assert.GreaterOrEqual(session.Playhead ?? 0, 11);
        }
    }
}
