using System.Collections.Generic;
using AgentTown.Simulation;
using NUnit.Framework;
using UnityEngine;

namespace AgentTown.Tests
{
    public sealed class RegionStatsTests
    {
        [Test]
        public void Compute_AggregatesMoodAndPopulationByRegion()
        {
            var agents = new Dictionary<string, SimAgentState>
            {
                ["a"] = new SimAgentState { AgentId = "a", Location = "广场", Mood = 0.8 },
                ["b"] = new SimAgentState { AgentId = "b", Location = "广场", Mood = 0.4 },
                ["c"] = new SimAgentState { AgentId = "c", Location = "市场", Mood = -0.5 },
            };
            var regions = new List<string> { "广场", "市场", "公园" };

            List<RegionStat> stats = RegionStats.Compute(agents, regions);
            Assert.AreEqual(3, stats.Count);

            RegionStat square = stats.Find(s => s.Id == "广场");
            Assert.AreEqual(2, square.Population);
            Assert.AreEqual(0.6, square.AvgMood, 1e-6);
            Assert.AreEqual(2f / 3f, square.PopulationRatio, 1e-5f);

            RegionStat market = stats.Find(s => s.Id == "市场");
            Assert.AreEqual(1, market.Population);
            Assert.AreEqual(-0.5, market.AvgMood, 1e-6);

            RegionStat park = stats.Find(s => s.Id == "公园");
            Assert.AreEqual(0, park.Population);
            Assert.AreEqual(0.0, park.AvgMood, 1e-6);
        }

        [Test]
        public void MoodBand_AndHeatmapColor_MatchDesktopBands()
        {
            Assert.AreEqual(MoodBand.Good, RegionStats.MoodBandOf(0.5));
            Assert.AreEqual(MoodBand.Bad, RegionStats.MoodBandOf(-0.5));
            Assert.AreEqual(MoodBand.Medium, RegionStats.MoodBandOf(0.0));

            Color good = RegionStats.MoodHeatmapColor(0.5, 0.5f);
            Assert.Greater(good.a, 0.2f);
            Assert.Greater(good.g, good.r);

            Color empty = RegionStats.MoodHeatmapColor(0.0, 0f);
            Assert.AreEqual(0.12f, empty.a, 1e-4f);
        }
    }
}
