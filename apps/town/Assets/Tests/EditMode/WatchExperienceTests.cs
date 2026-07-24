using System.Collections.Generic;
using AgentTown.Simulation;
using AgentTown.Town;
using AgentTown.UI;
using NUnit.Framework;
using UnityEngine;

namespace AgentTown.Tests
{
    public sealed class WatchExperienceTests
    {
        [Test]
        public void OverlayAlpha_Offline_HoldsThenFades_SpeedShortens()
        {
            var ix = new ActiveInteraction { Id = "c1", Tick = 3, Kind = "conversation" };
            int hold = InteractionModel.OfflineHoldTicks("conversation", 1f);
            int fade = InteractionModel.OfflineFadeTicks(1f);
            Assert.GreaterOrEqual(hold, 3, "conversation hold covers multi-line bubbles");

            Assert.AreEqual(1f, InteractionModel.OverlayAlpha(ix, 3, offline: true, 1f));
            Assert.AreEqual(1f, InteractionModel.OverlayAlpha(ix, 3 + hold, offline: true, 1f), 0.001f);

            float midFade = InteractionModel.OverlayAlpha(ix, 3 + hold + 1, offline: true, 1f);
            Assert.Greater(midFade, 0f);
            Assert.Less(midFade, 1f);

            Assert.AreEqual(0f, InteractionModel.OverlayAlpha(ix, 3 + hold + fade + 1, offline: true, 1f));

            // 4× shortens hold — age 1 already past hold at high speed for trade.
            var trade = new ActiveInteraction { Id = "t1", Tick = 6, Kind = "trade" };
            int hold4x = InteractionModel.OfflineHoldTicks("trade", 4f);
            Assert.AreEqual(1, hold4x);
            Assert.AreEqual(1f, InteractionModel.OverlayAlpha(trade, 6, offline: true, 4f));
            Assert.Less(
                InteractionModel.OverlayAlpha(trade, 6 + hold4x + 1, offline: true, 4f),
                1f);
        }

        [Test]
        public void OverlayAlpha_Live_AlwaysOpaque()
        {
            var ix = new ActiveInteraction { Id = "c1", Tick = 1, Kind = "conversation" };
            Assert.AreEqual(1f, InteractionModel.OverlayAlpha(ix, 99, offline: false, 1f));
        }

        [Test]
        public void WorldEventFeedback_MapsRegionsAndBanner()
        {
            var events = new List<WorldEvent>
            {
                new WorldEvent
                {
                    EventId = "demo-storm",
                    Kind = "storm",
                    EventType = "storm",
                    Title = "暴风雨来袭",
                    Description = "居民倾向回家",
                },
            };

            Assert.IsTrue(WorldEventFeedback.TryResolveBanner(events, null, out WorldEventFeedback.Banner banner));
            Assert.AreEqual("暴风雨来袭", banner.Title);
            Assert.AreEqual("居民倾向回家", banner.Subtitle);
            Assert.AreEqual("storm", banner.ToneId);

            IReadOnlyList<string> regions = WorldEventFeedback.HighlightRegions(events, null);
            CollectionAssert.Contains(regions, "住宅区");
            CollectionAssert.Contains(regions, "广场");

            var mods = new WorldModifiers { FestivalActive = true, MarketPriceMultiplier = 1.5 };
            IReadOnlyList<string> fromMods = WorldEventFeedback.HighlightRegions(null, mods);
            CollectionAssert.Contains(fromMods, "广场");
            CollectionAssert.Contains(fromMods, "市场");
        }

        [Test]
        public void WorldEventFeedback_PrefersDramaticEvent_AndCarriesDescription()
        {
            var events = new List<WorldEvent>
            {
                new WorldEvent
                {
                    EventId = "demo-festival",
                    Kind = "festival",
                    EventType = "festival",
                    Title = "节日庆典",
                    Description = "广场热闹",
                },
                new WorldEvent
                {
                    EventId = "demo-price",
                    Kind = "price_surge",
                    EventType = "price_surge",
                    Title = "市场物价上涨",
                    Description = "赵老板与王婶的进货渠道同时告急，日用品与青菜价格飙升，市场人心浮动。",
                },
            };

            Assert.IsTrue(WorldEventFeedback.TryResolveBanner(events, null, out WorldEventFeedback.Banner banner));
            Assert.AreEqual("市场物价上涨", banner.Title);
            Assert.IsTrue(banner.Subtitle.Contains("进货") || banner.Subtitle.Contains("价格"));
            Assert.AreEqual("price", banner.ToneId);
        }

        [Test]
        public void ConversationTtl_AndBubbleHeight_SupportMultiLine()
        {
            Assert.GreaterOrEqual(InteractionModel.TtlForKind("conversation"), 8f);
            Assert.Less(InteractionModel.TtlForKind("trade"), InteractionModel.TtlForKind("conversation"));

            float one = InteractionModel.BubbleHeightPx("一行");
            float three = InteractionModel.BubbleHeightPx("一\n二\n三");
            Assert.Greater(three, one);
            Assert.GreaterOrEqual(three, 120f);
        }

        [Test]
        public void OfflineDemo_ZhaoWangRelation_DipsAtOutbreak_RecoversAtReconcile()
        {
            var personas = new List<LocalPersona>
            {
                new LocalPersona
                {
                    AgentId = "zhao",
                    Name = "赵老板",
                    Role = "杂货商",
                    Home = "市场",
                    Relationships = new Dictionary<string, double> { ["wang"] = -0.4 },
                },
                new LocalPersona
                {
                    AgentId = "wang",
                    Name = "王婶",
                    Role = "菜贩",
                    Home = "市场",
                    Relationships = new Dictionary<string, double> { ["zhao"] = -0.4 },
                },
            };
            var regions = new Dictionary<string, WireVec3>
            {
                ["市场"] = new WireVec3(36, 0, 0),
                ["广场"] = new WireVec3(0, 0, 0),
            };

            OfflineDemoPack pack = OfflineDemoBuilder.Build(personas, regions, frameCount: 27);
            double seed = -0.4;
            double at1 = pack.Frames[0].Agents["zhao"].Relationships["wang"];
            double atOutbreak = pack.Frames[8].Agents["zhao"].Relationships["wang"]; // tick 9
            double atReconcile = pack.Frames[23].Agents["zhao"].Relationships["wang"]; // tick 24 和解

            Assert.AreEqual(seed, at1, 1e-4, "tick1 keeps persona seed");
            Assert.Less(atOutbreak, seed, "爆发拍 relation below seed");
            Assert.Greater(atReconcile, atOutbreak, "和解拍 relation recovers from trough");

            double moodOutbreak = pack.Frames[8].Agents["zhao"].Mood;
            double moodReconcile = pack.Frames[23].Agents["zhao"].Mood;
            Assert.Less(moodOutbreak, moodReconcile, "mood recovers with 和解");

            // ActiveEvents @ tick 6 carry long price_surge description for the banner.
            SimTickSnapshot tick6 = pack.Frames[5];
            Assert.IsTrue(WorldEventFeedback.TryResolveBanner(
                tick6.ActiveEvents, tick6.Modifiers, out WorldEventFeedback.Banner banner));
            Assert.AreEqual("市场物价上涨", banner.Title);
            Assert.IsTrue(banner.Subtitle.Contains("进货") || banner.Subtitle.Contains("价格"));

            // Festival window aligns with later arc (world_event @18 / 和解 @24).
            SimTickSnapshot tick20 = pack.Frames[19];
            Assert.IsTrue(tick20.Modifiers.FestivalActive);
        }

        [Test]
        public void SeekNextStoryTick_SkipsTickNoise()
        {
            OfflineDemoPack pack = BuildTinyPack();
            var session = new SimulationSession();
            session.EnterOfflineDemo(pack);

            Assert.AreEqual(1, session.DisplayTick);
            Assert.IsTrue(session.SeekNextStoryTick());
            Assert.AreEqual(3, session.DisplayTick, "first pulse is conversation @3");
            Assert.IsFalse(session.Playing, "seek pauses for readability");

            Assert.IsTrue(session.SeekNextStoryTick());
            Assert.AreEqual(6, session.DisplayTick, "trade + world_event @6");

            Assert.IsTrue(session.SeekNextStoryTick());
            Assert.AreEqual(9, session.DisplayTick, "outbreak conversation @9");
        }

        [Test]
        public void FpsSampler_WindowAndBands()
        {
            var sampler = new FpsSampler(windowSeconds: 0.5f);
            Assert.IsFalse(sampler.HasSample);
            Assert.AreEqual("— FPS", FpsSampler.FormatLabel(-1f));

            // 30 FPS → 0.5s window needs ~15 frames of 1/30s
            for (int i = 0; i < 14; i++)
            {
                Assert.IsFalse(sampler.AddFrame(1f / 30f));
            }

            Assert.IsTrue(sampler.AddFrame(1f / 30f));
            Assert.GreaterOrEqual(sampler.LastFps, 29f);
            Assert.AreEqual(FpsSampler.Band.Ok, sampler.LastBand);
            Assert.AreEqual("fps-ok", FpsSampler.BandClass(sampler.LastBand));

            Assert.AreEqual(FpsSampler.Band.Warn, FpsSampler.Classify(25f));
            Assert.AreEqual(FpsSampler.Band.Critical, FpsSampler.Classify(15f));
            Assert.AreEqual("30 FPS", FpsSampler.FormatLabel(30f));
        }

        [Test]
        public void BuildingLod_LevelForDistance()
        {
            Assert.AreEqual(
                0,
                TownBuildingLod.LevelForDistance(
                    10f,
                    TownBuildingLod.DefaultLowDetailDistance,
                    TownBuildingLod.DefaultCullDistance));
            Assert.AreEqual(
                1,
                TownBuildingLod.LevelForDistance(
                    40f,
                    TownBuildingLod.DefaultLowDetailDistance,
                    TownBuildingLod.DefaultCullDistance));
            Assert.AreEqual(
                2,
                TownBuildingLod.LevelForDistance(
                    90f,
                    TownBuildingLod.DefaultLowDetailDistance,
                    TownBuildingLod.DefaultCullDistance));
        }

        [Test]
        public void NatureLod_CullsSoonerThanBuildings()
        {
            // Nature skips LodLow cubes (low == cull → levels 0/2 only) and culls sooner than buildings.
            Assert.AreEqual(
                TownBuildingLod.NatureLowDetailDistance,
                TownBuildingLod.NatureCullDistance);
            Assert.Less(TownBuildingLod.NatureCullDistance, TownBuildingLod.DefaultCullDistance);
            Assert.Less(
                TownBuildingLod.NatureMicroCullDistance,
                TownBuildingLod.NatureCullDistance);
            Assert.AreEqual(0, TownBuildingLod.LevelForDistance(
                TownVisualLayout.BirdZoomDefaultDistance,
                TownBuildingLod.NatureLowDetailDistance,
                TownBuildingLod.NatureCullDistance));
            // Far foliage drops in bird view (mid-near canopy stays fuller after LOD relax).
            Assert.AreEqual(2, TownBuildingLod.LevelForDistance(
                70f, TownBuildingLod.NatureLowDetailDistance, TownBuildingLod.NatureCullDistance));
            Assert.AreEqual(2, TownBuildingLod.LevelForDistance(
                90f, TownBuildingLod.NatureLowDetailDistance, TownBuildingLod.NatureCullDistance));
            Assert.AreEqual(2, TownBuildingLod.LevelForDistance(
                40f,
                TownBuildingLod.NatureMicroLowDetailDistance,
                TownBuildingLod.NatureMicroCullDistance));
        }

        [Test]
        public void BuildingLod_Ensure_AttachesWithoutThrow()
        {
            GameObject go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = "LodBuilding";
            try
            {
                TownBuildingLod lod = null;
                Assert.DoesNotThrow(() => lod = TownBuildingLod.Ensure(go));
                Assert.IsNotNull(lod);
                Assert.IsNotNull(go.transform.Find("LodLow"));

                lod.ApplyLevel(1, force: true);
                Assert.IsTrue(go.transform.Find("LodLow").gameObject.activeSelf);

                lod.ApplyLevel(2, force: true);
                Assert.IsFalse(go.transform.Find("LodLow").gameObject.activeSelf);

                lod.ApplyLevel(0, force: true);
                Assert.IsFalse(go.transform.Find("LodLow").gameObject.activeSelf);
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }

        [Test]
        public void NatureLod_EnsureNature_AttachesWithoutThrow()
        {
            GameObject go = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            go.name = "LodTree";
            try
            {
                TownBuildingLod lod = null;
                Assert.DoesNotThrow(() => lod = TownBuildingLod.EnsureNature(go, aggressive: true));
                Assert.IsNotNull(lod);
                Assert.IsNotNull(go.transform.Find("LodLow"));
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }

        [Test]
        public void SimEventFilters_StoryBeat()
        {
            Assert.IsTrue(SimEventFilters.IsStoryBeat("sim.interaction"));
            Assert.IsTrue(SimEventFilters.IsStoryBeat("sim.world_event"));
            Assert.IsFalse(SimEventFilters.IsStoryBeat("sim.tick_started"));
            Assert.IsFalse(SimEventFilters.IsStoryBeat("sim.tick_ended"));
        }

        [Test]
        public void NpcManager_LivePosition_FallsBackToSnapshot()
        {
            var session = new SimulationSession();
            OfflineDemoPack pack = BuildTinyPack();
            session.EnterOfflineDemo(pack);

            // Without a spawned TownNpc, TryGetLiveWorldPosition still resolves via snapshot.
            var go = new GameObject("NpcMgrTest");
            try
            {
                TownNpcManager mgr = go.AddComponent<TownNpcManager>();
                mgr.Bind(session, null);
                Assert.IsTrue(session.AgentUnityPositions.Count > 0);
                string anyId = null;
                foreach (string key in session.AgentUnityPositions.Keys)
                {
                    anyId = key;
                    break;
                }

                Assert.IsNotNull(anyId);
                // SyncNpcs creates NPCs — live transform should resolve.
                Assert.IsTrue(mgr.TryGetLiveWorldPosition(anyId, out Vector3 live));
                Assert.IsTrue(mgr.TryGetNpc(anyId, out TownNpc npc));
                Assert.AreEqual(npc.transform.position, live);
            }
            finally
            {
                Object.DestroyImmediate(go);
            }
        }

        private static OfflineDemoPack BuildTinyPack()
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
            return OfflineDemoBuilder.Build(personas, regions, frameCount: 16);
        }
    }
}
