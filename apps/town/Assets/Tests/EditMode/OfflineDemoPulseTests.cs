using System.Collections.Generic;
using System.IO;
using System.Linq;
using AgentTown.Simulation;
using AgentTown.Town;
using NUnit.Framework;

namespace AgentTown.Tests
{
    public sealed class OfflineDemoPulseTests
    {
        [SetUp]
        public void SetUp()
        {
            // Prefer JSON SoT for every Build assertion in this fixture.
            DemoStoryPackCatalog.ResetForTests();
            DemoStoryPackCatalog.EnsureLoadedForBuild();
            Assert.IsTrue(
                DemoStoryPackCatalog.Loaded,
                $"Offline JSON SoT missing/unreadable — expected at {DemoStoryPackCatalog.AssetsFixturePath}");
        }

        [Test]
        public void DemoStoryPackJson_ExistsWithThreePacks()
        {
            Assert.IsTrue(File.Exists(DemoStoryPackCatalog.AssetsFixturePath)
                || File.Exists(DemoStoryPackCatalog.DefaultFixturePath),
                "demo-story-packs.json must ship under StreamingAssets/Fixtures");

            Assert.IsTrue(DemoStoryPackCatalog.TryGet(DemoPackIds.PriceSurge, out DemoStoryPackDef surge));
            Assert.IsTrue(DemoStoryPackCatalog.TryGet(DemoPackIds.Festival, out DemoStoryPackDef fest));
            Assert.IsTrue(DemoStoryPackCatalog.TryGet(DemoPackIds.TownHall, out DemoStoryPackDef hall));

            Assert.AreEqual(9, surge.Beats.Length, "price_surge nine beats");
            Assert.AreEqual(6, fest.Beats.Length, "festival six beats");
            Assert.AreEqual(6, hall.Beats.Length, "town_hall six beats");
            Assert.AreEqual(27, surge.FrameCount);
            Assert.AreEqual("涨价风波·试探", surge.Beats[0].ArcLabel);
            Assert.IsFalse(string.IsNullOrEmpty(surge.Synopsis), "pack synopsis for intro card");
            Assert.IsTrue(surge.Cast != null && surge.Cast.Length >= 2, "pack cast for intro card");
            Assert.IsFalse(string.IsNullOrEmpty(surge.Beats[0].WorldBlurb), "opening beat has world_blurb");
            Assert.IsFalse(
                string.IsNullOrEmpty(surge.Beats[0].ResolvedNarration),
                "opening beat has transition/narration");
            Assert.IsTrue(
                surge.Beats[0].Lines != null
                && surge.Beats[0].Lines.Length > 0
                && surge.Beats[0].Lines[0].Text.Contains("青菜"));
            CollectionAssert.AreEqual(
                new[] { "conversation", "trade", "conversation", "trade", "conversation", "vote",
                    "conversation", "trade", "conversation" },
                surge.Beats.Select(b => b.Kind).ToArray());
            CollectionAssert.AreEqual(
                new[] { "conversation", "trade", "conversation", "trade", "conversation", "conversation" },
                fest.Beats.Select(b => b.Kind).ToArray());
            Assert.AreEqual("vote", hall.Beats[3].Kind);
        }

        [Test]
        public void DemoPulse_NarrationEvents_ExistBetweenBeats()
        {
            OfflineDemoPack pack = OfflineDemoBuilder.Build(
                RivalRoster(), RivalRegions(), packId: DemoPackIds.PriceSurge);

            List<SimTickEvent> narrations = pack.Events
                .Where(e => e.Type == "sim.narration")
                .OrderBy(e => e.Tick)
                .ToList();
            Assert.GreaterOrEqual(narrations.Count, 8, "inter-beat + pulse narrations");
            Assert.IsTrue(narrations.Any(e => e.Tick == 4 || e.Tick == 5), "non-dialogue tick has narration");
            Assert.IsTrue(narrations.All(e => !string.IsNullOrEmpty(e.Detail)), "narration detail non-empty");

            // ActiveEvents / banner copy stays rich on atmosphere ticks.
            SimTickSnapshot tick6 = pack.Frames[5];
            Assert.IsTrue(tick6.ActiveEvents != null && tick6.ActiveEvents.Count > 0);
            Assert.IsTrue(tick6.ActiveEvents.Any(ev =>
                !string.IsNullOrEmpty(ev.Description) && ev.Description.Length > 10));
        }

        [Test]
        public void DemoPulse_LeadThoughts_MatchStoryArc()
        {
            OfflineDemoPack pack = OfflineDemoBuilder.Build(
                RivalRoster(), RivalRegions(), packId: DemoPackIds.PriceSurge);

            SimAgentState zhaoAt3 = pack.Frames[2].Agents["zhao"];
            Assert.IsFalse(string.IsNullOrEmpty(zhaoAt3.LastThought));
            Assert.IsFalse(zhaoAt3.LastThought.StartsWith("前往"), "story pulse should not be generic travel");
            Assert.IsTrue(
                zhaoAt3.LastThought.Contains("青菜")
                || zhaoAt3.LastThought.Contains("进货")
                || zhaoAt3.LastThought.Contains("王婶"),
                zhaoAt3.LastThought);

            SimAgentState wangAt9 = pack.Frames[8].Agents["wang"];
            Assert.IsTrue(
                wangAt9.LastThought.Contains("哄抬")
                || wangAt9.LastThought.Contains("脏水")
                || wangAt9.LastThought.Contains("摊位")
                || wangAt9.LastThought.Contains("涨价"),
                wangAt9.LastThought);
        }

        [Test]
        public void DemoPulse_MatchesScriptedCadence()
        {
            var personas = new List<LocalPersona>
            {
                new LocalPersona { AgentId = "lin", Name = "林小梅", Role = "面包师", Home = "面包店" },
                new LocalPersona { AgentId = "chen", Name = "陈大爷", Role = "退休教师", Home = "公园" },
            };
            var regions = new Dictionary<string, WireVec3>
            {
                ["广场"] = new WireVec3(0, 0, 0),
                ["市场"] = new WireVec3(36, 0, 0),
                ["面包店"] = new WireVec3(36, 0, -22),
                ["公园"] = new WireVec3(-18, 0, 6),
            };

            OfflineDemoPack pack = OfflineDemoBuilder.Build(personas, regions, frameCount: 27);

            // Every 3 ticks: story pulse; vote is beat 6 @ tick 18 (not a side add-on).
            Assert.AreEqual(9, pack.Interactions.Count, "nine thickened-arc pulses");
            Assert.AreEqual("conversation", KindAt(pack, 3));
            Assert.AreEqual("trade", KindAt(pack, 6));
            Assert.AreEqual("conversation", KindAt(pack, 9));
            Assert.AreEqual("trade", KindAt(pack, 12));
            Assert.AreEqual("conversation", KindAt(pack, 15));
            Assert.AreEqual("vote", KindAt(pack, 18));
            Assert.AreEqual("conversation", KindAt(pack, 21));
            Assert.AreEqual("trade", KindAt(pack, 24));
            Assert.AreEqual("conversation", KindAt(pack, 27));

            // World events every 6 ticks (plus ActiveEvents still carry festival windows).
            List<SimTickEvent> worldEvents = pack.Events
                .Where(e => e.Type == "sim.world_event")
                .OrderBy(e => e.Tick)
                .ToList();
            Assert.GreaterOrEqual(worldEvents.Count, 3);
            Assert.IsTrue(worldEvents.Any(e => e.Tick == 6));
            Assert.IsTrue(worldEvents.Any(e => e.Tick == 12));
            Assert.IsTrue(worldEvents.Any(e => e.Tick == 18));
            Assert.AreEqual("市场物价上涨", worldEvents[0].Summary, "first world_event is price_surge");
        }

        [Test]
        public void DemoPulse_PriceSurgeArc_TranscriptAndRivals()
        {
            var personas = new List<LocalPersona>
            {
                new LocalPersona { AgentId = "lin", Name = "林小梅", Role = "面包师", Home = "面包店" },
                new LocalPersona { AgentId = "zhao", Name = "赵老板", Role = "杂货商", Home = "市场" },
                new LocalPersona { AgentId = "wang", Name = "王婶", Role = "菜贩", Home = "市场" },
                new LocalPersona { AgentId = "liu", Name = "刘警官", Role = "镇派出所民警", Home = "广场" },
                new LocalPersona { AgentId = "chen", Name = "陈大爷", Role = "退休教师", Home = "公园" },
            };
            var regions = new Dictionary<string, WireVec3>
            {
                ["广场"] = new WireVec3(0, 0, 0),
                ["市场"] = new WireVec3(36, 0, 0),
                ["面包店"] = new WireVec3(36, 0, -22),
                ["公园"] = new WireVec3(-18, 0, 6),
            };

            OfflineDemoPack pack = OfflineDemoBuilder.Build(personas, regions, frameCount: 27);

            ActiveInteraction probe = pack.Interactions.First(i => i.Tick == 3 && i.Kind == "conversation");
            Assert.AreEqual("zhao", probe.InitiatorId);
            Assert.AreEqual("wang", probe.TargetId);
            Assert.GreaterOrEqual(probe.Transcript.Count, 3, "试探 beat has multi-line transcript");
            Assert.IsTrue(probe.Summary.Contains("涨价风波·试探"));
            Assert.IsTrue(probe.Transcript[0].Text.Contains("青菜") || probe.Transcript[0].Text.Contains("进货"));

            SimTickEvent convEvt = pack.Events.First(e => e.Type == "sim.interaction" && e.Tick == 3);
            Assert.IsFalse(string.IsNullOrEmpty(convEvt.Detail));
            Assert.IsTrue(convEvt.Detail.Contains("："));
            Assert.GreaterOrEqual(convEvt.Detail.Split('\n').Length, 3);

            ActiveInteraction surgeTrade = pack.Interactions.First(i => i.Tick == 6 && i.Kind == "trade");
            Assert.IsTrue(surgeTrade.Summary.Contains("涨价风波·趁乱"));
            Assert.GreaterOrEqual(surgeTrade.Transcript.Count, 3);

            ActiveInteraction mediation = pack.Interactions.First(i => i.Tick == 15 && i.Kind == "conversation");
            Assert.IsTrue(mediation.Summary.Contains("调解"));
            Assert.IsTrue(mediation.Transcript.Any(l => l.SpeakerId == "liu" || l.Text.Contains("刘警官")));

            ActiveInteraction vote = pack.Interactions.First(i => i.Tick == 18 && i.Kind == "vote");
            Assert.IsTrue(vote.Summary.Contains("表决") || vote.Summary.Contains("投票"));
            Assert.IsTrue(vote.Summary.Contains("夜市") || vote.Summary.Contains("限价"));

            List<SimTickEvent> worldEvents = pack.Events
                .Where(e => e.Type == "sim.world_event")
                .OrderBy(e => e.Tick)
                .ToList();
            Assert.AreEqual("市场物价上涨", worldEvents[0].Summary);
            Assert.IsTrue(worldEvents[0].Detail.Contains("涨") || worldEvents[0].Detail.Contains("价格"));
            Assert.AreEqual("暴风雨来袭", worldEvents[1].Summary);

            // Full nine-beat arc within 27 frames: …24 和解, 27 巩固.
            Assert.IsTrue(pack.Interactions.Any(i => i.Tick == 24 && i.Kind == "trade"));
            Assert.IsTrue(
                pack.Interactions.First(i => i.Tick == 24 && i.Kind == "trade").Summary.Contains("和解"));
            Assert.IsTrue(
                pack.Interactions.First(i => i.Tick == 27).Summary.Contains("巩固"));

            // Story decisions land in the Decisions list (not only idle move_to).
            Assert.IsTrue(pack.Decisions.Any(d =>
                d.ActionType == "conversation" || d.ActionType == "trade" || d.ActionType == "vote"));
            Assert.IsTrue(pack.Decisions.Any(d =>
                (d.Summary ?? "").Contains("涨价风波") || (d.Summary ?? "").Contains("投票")));
        }

        [Test]
        public void SimEventFilters_HidesTickNoise()
        {
            Assert.IsTrue(SimEventFilters.IsTickNoise("sim.tick_started"));
            Assert.IsTrue(SimEventFilters.IsTickNoise("sim.tick_ended"));
            Assert.IsFalse(SimEventFilters.IsTickNoise("sim.interaction"));
            Assert.IsFalse(SimEventFilters.IsTickNoise("sim.world_event"));
            Assert.IsTrue(SimEventFilters.IsStoryEvent("sim.interaction"));
            Assert.IsFalse(SimEventFilters.IsStoryEvent("sim.tick_started"));
            Assert.IsTrue(SimEventFilters.IsStoryBeat("sim.interaction"));
            Assert.IsTrue(SimEventFilters.IsStoryBeat("sim.world_event"));
            Assert.IsFalse(SimEventFilters.IsStoryBeat("sim.tick_started"));
        }

        [Test]
        public void DemoPulse_FestivalPack_SixBeatsAndFestivalWorld()
        {
            OfflineDemoPack pack = OfflineDemoBuilder.Build(
                RivalRoster(), RivalRegions(), packId: DemoPackIds.Festival);

            Assert.AreEqual(DemoPackIds.Festival, pack.PackId);
            Assert.AreEqual(6, pack.Interactions.Count, "festival pack has six pulses");
            Assert.AreEqual("conversation", KindAt(pack, 3));
            Assert.AreEqual("trade", KindAt(pack, 6));
            Assert.AreEqual("conversation", KindAt(pack, 9));
            Assert.AreEqual("trade", KindAt(pack, 12));
            Assert.AreEqual("conversation", KindAt(pack, 15));
            Assert.AreEqual("conversation", KindAt(pack, 18));
            Assert.IsTrue(pack.Interactions[0].Summary.Contains("节日庆典"));

            List<SimTickEvent> worldEvents = pack.Events
                .Where(e => e.Type == "sim.world_event")
                .OrderBy(e => e.Tick)
                .ToList();
            Assert.GreaterOrEqual(worldEvents.Count, 1);
            Assert.AreEqual("节日庆典", worldEvents[0].Summary);
            Assert.IsTrue(pack.Frames.Any(f => f.Modifiers != null && f.Modifiers.FestivalActive));
        }

        [Test]
        public void DemoPulse_TownHallPack_IncludesRealVote()
        {
            OfflineDemoPack pack = OfflineDemoBuilder.Build(
                RivalRoster(), RivalRegions(), packId: DemoPackIds.TownHall);

            Assert.AreEqual(DemoPackIds.TownHall, pack.PackId);
            Assert.AreEqual(6, pack.Interactions.Count);
            Assert.AreEqual("vote", KindAt(pack, 12), "vote is beat 4 @ tick 12");
            ActiveInteraction vote = pack.Interactions.First(i => i.Kind == "vote");
            Assert.IsTrue(vote.Summary.Contains("镇民大会") || vote.Summary.Contains("表决"));
            Assert.IsTrue(pack.Interactions.Any(i => (i.Summary ?? "").Contains("镇政厅")));

            List<SimTickEvent> worldEvents = pack.Events
                .Where(e => e.Type == "sim.world_event")
                .OrderBy(e => e.Tick)
                .ToList();
            Assert.GreaterOrEqual(worldEvents.Count, 1);
            Assert.AreEqual("镇政厅公告", worldEvents[0].Summary);
        }

        [Test]
        public void DemoPulse_PackSwitch_ChangesStoryWithoutBreakingCadence()
        {
            OfflineDemoPack surge = OfflineDemoBuilder.Build(
                RivalRoster(), RivalRegions(), packId: DemoPackIds.PriceSurge);
            OfflineDemoPack fest = OfflineDemoBuilder.Build(
                RivalRoster(), RivalRegions(), packId: DemoPackIds.Festival);

            Assert.AreEqual(9, surge.Interactions.Count);
            Assert.AreEqual(6, fest.Interactions.Count);
            Assert.AreNotEqual(
                surge.Interactions[0].Summary,
                fest.Interactions[0].Summary,
                "different packs bake different opening beats");
            Assert.AreEqual(3, surge.Interactions[0].Tick);
            Assert.AreEqual(3, fest.Interactions[0].Tick);
        }

        private static List<LocalPersona> RivalRoster() =>
            new List<LocalPersona>
            {
                new LocalPersona { AgentId = "lin", Name = "林小梅", Role = "面包师", Home = "面包店" },
                new LocalPersona { AgentId = "zhao", Name = "赵老板", Role = "杂货商", Home = "市场" },
                new LocalPersona { AgentId = "wang", Name = "王婶", Role = "菜贩", Home = "市场" },
                new LocalPersona { AgentId = "liu", Name = "刘警官", Role = "镇派出所民警", Home = "广场" },
                new LocalPersona { AgentId = "chen", Name = "陈大爷", Role = "退休教师", Home = "公园" },
            };

        private static Dictionary<string, WireVec3> RivalRegions() =>
            new Dictionary<string, WireVec3>
            {
                ["广场"] = new WireVec3(0, 0, 0),
                ["市场"] = new WireVec3(36, 0, 0),
                ["面包店"] = new WireVec3(36, 0, -22),
                ["公园"] = new WireVec3(-18, 0, 6),
                ["镇政厅"] = new WireVec3(-12, 0, -18),
                ["图书馆"] = new WireVec3(-40, 0, -8),
                ["工坊"] = new WireVec3(48, 0, -36),
                ["码头"] = new WireVec3(-8, 0, 40),
                ["餐厅"] = new WireVec3(52, 0, 20),
                ["住宅区"] = new WireVec3(18, 0, 38),
            };

        [Test]
        public void DemoPulse_NewDistricts_GatherForOverlays()
        {
            OfflineDemoPack surge = OfflineDemoBuilder.Build(
                RivalRoster(), RivalRegions(), packId: DemoPackIds.PriceSurge);
            OfflineDemoPack fest = OfflineDemoBuilder.Build(
                RivalRoster(), RivalRegions(), packId: DemoPackIds.Festival);
            OfflineDemoPack hall = OfflineDemoBuilder.Build(
                RivalRoster(), RivalRegions(), packId: DemoPackIds.TownHall);

            // price_surge beat 3 @ tick 9 → 图书馆; beat 4 @ tick 12 → 码头
            Assert.AreEqual("图书馆", surge.Frames[8].Agents["zhao"].Location);
            Assert.AreEqual("图书馆", surge.Frames[8].Agents["wang"].Location);
            Assert.AreEqual("码头", surge.Frames[11].Agents["zhao"].Location);
            Assert.AreEqual("码头", surge.Frames[11].Agents["wang"].Location);

            // festival beat 4 @ tick 12 → 工坊
            Assert.AreEqual("工坊", fest.Frames[11].Agents["zhao"].Location);
            Assert.AreEqual("工坊", fest.Frames[11].Agents["wang"].Location);

            // town_hall beat 2 @ tick 6 → 图书馆
            Assert.AreEqual("图书馆", hall.Frames[5].Agents["zhao"].Location);
            Assert.AreEqual("图书馆", hall.Frames[5].Agents["wang"].Location);

            Assert.IsTrue(
                DemoStoryPackCatalog.TryGet(DemoPackIds.PriceSurge, out DemoStoryPackDef surgeDef)
                && surgeDef.Beats[2].Location == "图书馆"
                && surgeDef.Beats[3].Location == "码头");
        }

        private static string KindAt(OfflineDemoPack pack, int tick)
        {
            ActiveInteraction ix = pack.Interactions.FirstOrDefault(i => i.Tick == tick);
            Assert.IsNotNull(ix, $"missing pulse at tick {tick}");
            return ix.Kind;
        }
    }
}
