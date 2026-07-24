using System;
using System.Collections.Generic;
using AgentTown.Town;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Client-local offline / demo pack: scripted tick snapshots + sample decisions / events so
    /// AgentTown can be observed without a backend or LLM. Frames reuse the same
    /// <see cref="SimTickSnapshot"/> shape as live GET ticks; playback goes through
    /// <see cref="SimulationSession.ApplySnapshot"/> and the existing playhead.
    /// </summary>
    public sealed class OfflineDemoPack
    {
        public const string DemoRunId = "offline-demo";
        /// <summary>27 frames covers nine 涨价风波 beats (pulse @3…27; vote is beat 6 @18).</summary>
        public const int DefaultFrameCount = 27;

        public string RunId = DemoRunId;
        /// <summary>Story pack id (<see cref="DemoPackIds"/>); independent of REST scenario.</summary>
        public string PackId = DemoPackIds.PriceSurge;
        public RunManifest Manifest = new();
        public List<SimTickSnapshot> Frames = new();
        public List<SimDecision> Decisions = new();
        public List<SimTickEvent> Events = new();
        /// <summary>Per-tick interaction cues for 3D overlays (conversation / trade / vote).</summary>
        public List<ActiveInteraction> Interactions = new();
    }

    public static class OfflineDemoBuilder
    {
        private static readonly string[] TourStops =
        {
            "广场", "市场", "餐厅", "面包店", "公园", "住宅区", "镇政厅",
            "图书馆", "工坊", "码头",
        };

        private static readonly string[] Activities =
        {
            "闲逛", "赶路", "聊天", "工作", "休息", "采购", "散步",
        };

        /// <summary>
        /// Build a multi-frame demo from local personas + region anchors (wire space).
        /// Falls back to a single lin@市场 frame when personas / regions are empty.
        /// Frames include metrics, modifiers, and sample interactions for the chosen
        /// <paramref name="packId"/> (<see cref="DemoPackIds"/>; default 涨价风波).
        /// </summary>
        public static OfflineDemoPack Build(
            IReadOnlyList<LocalPersona> personas,
            IReadOnlyDictionary<string, WireVec3> regions,
            int frameCount = -1,
            string packId = null)
        {
            // JSON SoT: Fixtures/demo-story-packs.json (ensure loaded before Build in runtime).
            DemoStoryPackCatalog.EnsureLoadedForBuild();

            string resolvedPack = DemoPackIds.Normalize(packId);
            int resolvedFrames = frameCount > 0
                ? frameCount
                : DemoPackIds.DefaultFrameCount(resolvedPack);
            int count = Mathf.Clamp(resolvedFrames, 8, 30);
            var pack = new OfflineDemoPack { PackId = resolvedPack };
            StoryBeat[] beats = BeatsFor(resolvedPack);
            string[] worldPresets = WorldPresetsFor(resolvedPack);

            List<LocalPersona> roster = ResolveRoster(personas);
            Dictionary<string, WireVec3> anchors = ResolveAnchors(regions);

            pack.Manifest = BuildManifest(roster, anchors, resolvedPack);
            pack.Frames = new List<SimTickSnapshot>(count);
            pack.Decisions = new List<SimDecision>();
            pack.Events = new List<SimTickEvent>();
            pack.Interactions = new List<ActiveInteraction>();

            for (int tick = 1; tick <= count; tick++)
            {
                int hour = (8 + tick - 1) % 24;
                ResolveAtmosphere(resolvedPack, tick, out bool festival, out bool storm, out bool priceSurge);

                var snapshot = new SimTickSnapshot
                {
                    Tick = tick,
                    Hour = hour,
                    Agents = new Dictionary<string, SimAgentState>(),
                    Modifiers = new WorldModifiers
                    {
                        MarketPriceMultiplier = priceSurge ? 1.4 : 1.0,
                        StormActive = storm,
                        FestivalActive = festival,
                        SquareAttractionBoost = festival ? 0.35 : 0.0,
                    },
                    ActiveEvents = BuildActiveEvents(
                        resolvedPack, tick, festival, storm, priceSurge, beats),
                    Metrics = null,
                };

                var popByRegion = new Dictionary<string, int>();
                double moodSum = 0.0;
                int tradeCount = tick >= 4 && tick % 3 == 0 ? 1 : 0;

                for (int i = 0; i < roster.Count; i++)
                {
                    LocalPersona persona = roster[i];
                    string location = LocationFor(persona, i, tick, anchors);
                    WireVec3 wire = PositionFor(persona, location, anchors, tick, i);
                    string activity = Activities[(i + tick) % Activities.Length];
                    double mood = 0.15 + 0.05 * Math.Sin((tick + i) * 0.7);
                    if (festival)
                    {
                        mood += 0.2;
                    }

                    if (storm)
                    {
                        mood -= 0.25;
                    }

                    snapshot.Agents[persona.AgentId] = new SimAgentState
                    {
                        AgentId = persona.AgentId,
                        Name = persona.Name,
                        Role = persona.Role,
                        Location = location,
                        Position = wire,
                        Activity = activity,
                        Mood = mood,
                        Goal = persona.Goal ?? "",
                        LastThought = ThoughtFor(persona, tick, location, beats),
                        Money = 80 + i * 7,
                        Relationships = SeedRelationships(persona),
                    };

                    if (tick == 1 || (tick + i) % 3 == 0)
                    {
                        // Summary = short reason (activity / thought); Location + move_to drive the action clause.
                        string reason = tick == 1
                            ? $"从{persona.Home}出发"
                            : (!string.IsNullOrEmpty(activity) ? activity : $"前往{location}");
                        pack.Decisions.Add(new SimDecision
                        {
                            Tick = tick,
                            AgentId = persona.AgentId,
                            Summary = reason,
                            ActionType = "move_to",
                            Location = location,
                        });
                    }
                }

                // Story pulses: gather rivals (+ mediator) at beat.Location so overlays
                // are visible in 图书馆 / 工坊 / 码头 (and other named districts).
                GatherForStoryPulse(snapshot, roster, tick, beats, anchors);

                // Pack-specific rival mood / relation arcs.
                if (resolvedPack == DemoPackIds.PriceSurge)
                {
                    ApplyPriceSurgeArc(snapshot, roster, tick);
                }
                else if (resolvedPack == DemoPackIds.Festival)
                {
                    ApplyFestivalArc(snapshot, roster, tick);
                }
                else if (resolvedPack == DemoPackIds.TownHall)
                {
                    ApplyTownHallArc(snapshot, roster, tick);
                }

                moodSum = 0.0;
                foreach (KeyValuePair<string, SimAgentState> pair in snapshot.Agents)
                {
                    moodSum += pair.Value.Mood;
                    string location = pair.Value.Location ?? "";
                    if (!string.IsNullOrEmpty(location))
                    {
                        if (!popByRegion.ContainsKey(location))
                        {
                            popByRegion[location] = 0;
                        }

                        popByRegion[location]++;
                    }
                }

                snapshot.Metrics = new TickMetrics
                {
                    Tick = tick,
                    Hour = hour,
                    AvgMood = roster.Count > 0 ? moodSum / roster.Count : 0.0,
                    TradeCount = tradeCount,
                    TradeTotalAmount = tradeCount * (12.0 + tick),
                    PositiveRelationRatio = 0.35 + 0.02 * (tick % 5),
                    PopulationByRegion = popByRegion,
                };

                pack.Events.Add(new SimTickEvent
                {
                    Tick = tick,
                    Type = "sim.tick_started",
                    Summary = $"tick {tick} started",
                    Timestamp = $"2026-01-01T{hour:D2}:00:00.000Z",
                });

                AddNarrationEvents(pack, tick, hour, beats);
                AddDemoInteractions(pack, roster, tick, hour, beats, worldPresets);

                pack.Events.Add(new SimTickEvent
                {
                    Tick = tick,
                    Type = "sim.tick_ended",
                    Summary = $"tick {tick} ended · {snapshot.Agents.Count} agents",
                    Timestamp = $"2026-01-01T{hour:D2}:00:01.000Z",
                });

                pack.Frames.Add(snapshot);
            }

            // Newest-first to match live PushDecision / PushTickEvent ordering.
            pack.Decisions.Reverse();
            pack.Events.Reverse();
            return pack;
        }

        private static void ResolveAtmosphere(
            string packId, int tick, out bool festival, out bool storm, out bool priceSurge)
        {
            festival = false;
            storm = false;
            priceSurge = false;
            switch (DemoPackIds.Normalize(packId))
            {
                case DemoPackIds.Festival:
                    // Early gather → peak festival window.
                    festival = tick >= 6 && tick <= 18;
                    break;
                case DemoPackIds.TownHall:
                    // Light festival after the vote passes.
                    festival = tick >= 15 && tick <= 18;
                    break;
                default:
                    // price_surge: windows track scripted world_event cadence (6 / 12 / 18).
                    festival = tick >= 18 && tick <= 24;
                    storm = tick >= 12 && tick <= 14;
                    priceSurge = tick >= 3 && tick <= 9;
                    break;
            }
        }

        private static List<WorldEvent> BuildActiveEvents(
            string packId, int tick, bool festival, bool storm, bool priceSurge, StoryBeat[] beats)
        {
            var list = new List<WorldEvent>();
            string festivalBlurb = FindBlurb(beats, "节日", "庆典", "广场张灯")
                ?? "广场张灯结彩，节日庆典拉开帷幕。";
            string stormBlurb = FindBlurb(beats, "暴风", "雨", "避险")
                ?? "乌云压镇，狂风暴雨将至。";
            string priceBlurb = FindBlurb(beats, "价格", "涨价", "物价")
                ?? "市场物价上涨，人心浮动。";

            // Soft narration banner on quiet ticks (no atmosphere event).
            string beatNarration = FindNearestNarration(beats, tick);

            if (festival)
            {
                int start = packId == DemoPackIds.Festival ? 6
                    : packId == DemoPackIds.TownHall ? 15
                    : 18;
                list.Add(new WorldEvent
                {
                    EventId = "demo-festival",
                    Kind = "festival",
                    EventType = "festival",
                    Title = "节日庆典",
                    Description = festivalBlurb,
                    TickStarted = start,
                    DurationTicks = 7,
                    Source = "demo",
                });
            }

            if (storm)
            {
                list.Add(new WorldEvent
                {
                    EventId = "demo-storm",
                    Kind = "storm",
                    EventType = "storm",
                    Title = "暴风雨来袭",
                    Description = stormBlurb,
                    TickStarted = 12,
                    DurationTicks = 3,
                    Source = "demo",
                });
            }

            if (priceSurge)
            {
                list.Add(new WorldEvent
                {
                    EventId = "demo-price",
                    Kind = "price_surge",
                    EventType = "price_surge",
                    Title = "市场物价上涨",
                    Description = priceBlurb,
                    TickStarted = 3,
                    DurationTicks = 7,
                    Source = "demo",
                });
            }

            // Non-atmosphere ticks still carry a soft narration banner when we have copy.
            if (list.Count == 0 && !string.IsNullOrEmpty(beatNarration))
            {
                StoryBeat nearest = BeatAtOrBefore(beats, tick);
                list.Add(new WorldEvent
                {
                    EventId = $"demo-narration-{tick}",
                    Kind = "announcement",
                    EventType = "announcement",
                    Title = string.IsNullOrEmpty(nearest?.ArcLabel) ? "旁白" : nearest.ArcLabel,
                    Description = beatNarration,
                    TickStarted = tick,
                    DurationTicks = 1,
                    Source = "demo",
                });
            }

            return list;
        }

        private static string FindNearestNarration(StoryBeat[] beats, int tick)
        {
            StoryBeat beat = BeatAtOrBefore(beats, tick);
            if (beat == null)
            {
                return null;
            }

            if (!string.IsNullOrEmpty(beat.WorldBlurb))
            {
                return beat.WorldBlurb;
            }

            return string.IsNullOrEmpty(beat.Narration) ? null : beat.Narration;
        }

        /// <summary>Pulse cadence: beat i lands at tick (i+1)*3.</summary>
        private static StoryBeat BeatAtOrBefore(StoryBeat[] beats, int tick)
        {
            if (beats == null || beats.Length == 0 || tick < DemoPulseInterval)
            {
                return null;
            }

            int pulseIndex = tick / DemoPulseInterval;
            if (pulseIndex <= 0)
            {
                return null;
            }

            int idx = Math.Min(pulseIndex, beats.Length) - 1;
            return beats[idx];
        }

        private static StoryBeat BeatExactlyAt(StoryBeat[] beats, int tick)
        {
            if (beats == null || beats.Length == 0 || tick <= 0 || tick % DemoPulseInterval != 0)
            {
                return null;
            }

            int pulseIndex = tick / DemoPulseInterval;
            return beats[(pulseIndex - 1) % beats.Length];
        }

        /// <summary>
        /// Emit narration / transition on inter-beat ticks and reinforce pulse ticks
        /// so the events tab + banner stay readable between dialogues.
        /// </summary>
        private static void AddNarrationEvents(
            OfflineDemoPack pack, int tick, int hour, StoryBeat[] beats)
        {
            if (beats == null || beats.Length == 0)
            {
                return;
            }

            StoryBeat onPulse = BeatExactlyAt(beats, tick);
            if (onPulse != null)
            {
                string pulseText = !string.IsNullOrEmpty(onPulse.Narration)
                    ? onPulse.Narration
                    : onPulse.WorldBlurb;
                if (!string.IsNullOrEmpty(pulseText))
                {
                    pack.Events.Add(new SimTickEvent
                    {
                        Tick = tick,
                        Type = "sim.narration",
                        AgentId = "",
                        Summary = string.IsNullOrEmpty(onPulse.ArcLabel) ? "旁白" : onPulse.ArcLabel,
                        Detail = pulseText,
                        Timestamp = $"2026-01-01T{hour:D2}:00:00.080Z",
                    });
                }

                return;
            }

            // Between pulses: show the upcoming beat's transition (or last beat narration).
            int nextPulseTick = ((tick / DemoPulseInterval) + 1) * DemoPulseInterval;
            StoryBeat upcoming = BeatExactlyAt(beats, nextPulseTick);
            string bridge = upcoming != null && !string.IsNullOrEmpty(upcoming.Narration)
                ? upcoming.Narration
                : null;
            if (string.IsNullOrEmpty(bridge))
            {
                StoryBeat prev = BeatAtOrBefore(beats, tick);
                bridge = prev != null && !string.IsNullOrEmpty(prev.WorldBlurb)
                    ? prev.WorldBlurb
                    : prev?.Narration;
            }

            if (string.IsNullOrEmpty(bridge))
            {
                return;
            }

            string title = upcoming != null && !string.IsNullOrEmpty(upcoming.ArcLabel)
                ? $"过渡 · {upcoming.ArcLabel}"
                : "旁白";
            pack.Events.Add(new SimTickEvent
            {
                Tick = tick,
                Type = "sim.narration",
                AgentId = "",
                Summary = title,
                Detail = bridge,
                Timestamp = $"2026-01-01T{hour:D2}:00:00.080Z",
            });
        }

        private static string ThoughtFor(
            LocalPersona persona, int tick, string location, StoryBeat[] beats)
        {
            if (persona == null)
            {
                return "";
            }

            if (tick == 1)
            {
                return $"从{persona.Home}出发，看看今天镇上有什么动静。";
            }

            StoryBeat beat = BeatAtOrBefore(beats, tick);
            if (beat != null && IsStoryLead(persona.AgentId))
            {
                string storyThought = ThoughtForLead(persona.AgentId, beat, tick);
                if (!string.IsNullOrEmpty(storyThought))
                {
                    return storyThought;
                }
            }

            if (beat != null && !string.IsNullOrEmpty(beat.ArcLabel) && IsStoryLead(persona.AgentId))
            {
                return $"心里惦记着「{beat.ArcLabel}」，先往{location}走。";
            }

            return $"前往{location}，留意街上的风声。";
        }

        private static bool IsStoryLead(string agentId) =>
            agentId == RivalLeftId || agentId == RivalRightId || agentId == MediatorId;

        private static string ThoughtForLead(string agentId, StoryBeat beat, int tick)
        {
            if (beat == null)
            {
                return null;
            }

            string arc = beat.ArcLabel ?? "";
            string lineHint = FirstLineForSpeaker(beat, agentId);
            bool onPulse = tick > 0 && tick % DemoPulseInterval == 0;

            if (agentId == RivalLeftId)
            {
                if (arc.Contains("试探")) return onPulse
                    ? "王婶那批青菜价不对劲，我得当面问问。"
                    : "进货价在涨，得先摸清王婶的底。";
                if (arc.Contains("趁乱")) return onPulse
                    ? "渠道紧了就按市价收——谁先囤谁活。"
                    : "涨价风来了，日用品得抓紧囤。";
                if (arc.Contains("爆发")) return onPulse
                    ? "她当街泼脏水？我跟行情走，不怕吵。"
                    : "市场就这么大，嗓门解决不了进货。";
                if (arc.Contains("避险")) return onPulse
                    ? "暴风雨要来了，先弄到防水布再说旧账。"
                    : "天色不对，避险比吵架要紧。";
                if (arc.Contains("调解")) return onPulse
                    ? "刘警官说了算——涨价的事去镇政厅说。"
                    : "再吵要记警告，今晚得去镇政厅。";
                if (arc.Contains("表决")) return onPulse
                    ? "限价我支持——乱涨只会把市场吵散。"
                    : "表决在即，限价规矩得落纸面。";
                if (arc.Contains("收场")) return onPulse
                    ? "限价我认，至少规矩清楚，回摊守着。"
                    : "结果记档了，别再当街对骂。";
                if (arc.Contains("和解") || arc.Contains("巩固")) return onPulse
                    ? (arc.Contains("和解")
                        ? "节日平价换彩带，算和解——别再提涨价风。"
                        : "客流回来了，货正常出，比吵架强。")
                    : "市场太平点好，有事走镇政厅。";
                if (arc.Contains("邀约") || arc.Contains("备货") || arc.Contains("聚集")
                    || arc.Contains("互惠") || arc.Contains("干杯") || arc.Contains("余韵"))
                {
                    return onPulse && !string.IsNullOrEmpty(lineHint)
                        ? TruncateThought(lineHint)
                        : "广场张灯，节日里先把热闹办好。";
                }

                if (arc.Contains("公告") || arc.Contains("游说") || arc.Contains("辩论")
                    || arc.Contains("宣读") || arc.Contains("落定"))
                {
                    return onPulse && !string.IsNullOrEmpty(lineHint)
                        ? TruncateThought(lineHint)
                        : "镇民大会要是开成，限价规矩就能摆上台面。";
                }
            }

            if (agentId == RivalRightId)
            {
                if (arc.Contains("试探")) return onPulse
                    ? "赵老板少打听我的进货——老主顾等着要货。"
                    : "他盯着我的价，得护住自己的渠道。";
                if (arc.Contains("趁乱")) return onPulse
                    ? "市价？分明趁乱加码……先成交，账以后再算。"
                    : "涨价风里谁都想多捞，我不能吃哑巴亏。";
                if (arc.Contains("爆发")) return onPulse
                    ? "他吃了涨价红利还说我哄抬？今日必须说清楚。"
                    : "再这样连他摊位都不让过。";
                if (arc.Contains("避险")) return onPulse
                    ? "暴风雨里谁都别想赚痛快钱——防水布拿去。"
                    : "雨要来了，先顾避险，进货的事暂搁。";
                if (arc.Contains("调解")) return onPulse
                    ? "各卖各的。涨价的事，雨停了去镇政厅说。"
                    : "刘警官出面了，今晚表决我得在场。";
                if (arc.Contains("表决")) return onPulse
                    ? "限价比互相泼脏水强——我也支持。"
                    : "投票比吵架强，限价我认。";
                if (arc.Contains("收场")) return onPulse
                    ? "我也认。下次有事直接去镇政厅。"
                    : "规矩清楚就行，回摊做生意。";
                if (arc.Contains("和解") || arc.Contains("巩固")) return onPulse
                    ? (arc.Contains("和解")
                        ? "看在节日份上，平价就平价，别再提涨价。"
                        : "客流回来了，青菜也别再卡他老主顾。")
                    : "节日里和解，比任何公告都管用。";
                if (arc.Contains("邀约") || arc.Contains("备货") || arc.Contains("聚集")
                    || arc.Contains("互惠") || arc.Contains("干杯") || arc.Contains("余韵"))
                {
                    return onPulse && !string.IsNullOrEmpty(lineHint)
                        ? TruncateThought(lineHint)
                        : "节日嘛，谁不乐意热闹——先把庆典办好。";
                }

                if (arc.Contains("公告") || arc.Contains("游说") || arc.Contains("辩论")
                    || arc.Contains("宣读") || arc.Contains("落定"))
                {
                    return onPulse && !string.IsNullOrEmpty(lineHint)
                        ? TruncateThought(lineHint)
                        : "开会可以，但得保证菜贩有发言席。";
                }
            }

            if (agentId == MediatorId)
            {
                if (arc.Contains("调解") || arc.Contains("收场") || arc.Contains("表决")
                    || arc.Contains("宣读") || arc.Contains("辩论") || arc.Contains("公告"))
                {
                    return onPulse && !string.IsNullOrEmpty(lineHint)
                        ? TruncateThought(lineHint)
                        : "用投票，别用嗓门——镇政厅见。";
                }

                if (arc.Contains("聚集") || arc.Contains("干杯") || arc.Contains("余韵"))
                {
                    return "今晚先把庆典办好，别吵进货。";
                }

                return "巡一圈市场，别让纠纷再当街炸开。";
            }

            return null;
        }

        private static string FirstLineForSpeaker(StoryBeat beat, string agentId)
        {
            if (beat?.Lines == null)
            {
                return null;
            }

            string code = agentId == RivalRightId ? "b"
                : agentId == MediatorId ? "m"
                : "a";
            foreach ((string speaker, string text) in beat.Lines)
            {
                if (speaker == code && !string.IsNullOrEmpty(text))
                {
                    return text;
                }
            }

            return null;
        }

        private static string TruncateThought(string text)
        {
            if (string.IsNullOrEmpty(text))
            {
                return "";
            }

            const int max = 36;
            string t = text.Trim();
            if (t.Length <= max)
            {
                return t;
            }

            return t.Substring(0, max) + "…";
        }

        private static string FindBlurb(StoryBeat[] beats, params string[] tokens)
        {
            if (beats == null)
            {
                return null;
            }

            foreach (StoryBeat beat in beats)
            {
                if (string.IsNullOrEmpty(beat?.WorldBlurb))
                {
                    continue;
                }

                foreach (string token in tokens)
                {
                    if (beat.WorldBlurb.Contains(token))
                    {
                        return beat.WorldBlurb;
                    }
                }
            }

            return null;
        }

        /// <summary>
        /// Cumulative Zhao↔Wang relation + mood along the nine-beat arc.
        /// Seed from persona; 爆发 dips below seed; 和解/巩固 recovers above the trough.
        /// </summary>
        private static void ApplyPriceSurgeArc(
            SimTickSnapshot snapshot, List<LocalPersona> roster, int tick)
        {
            if (snapshot?.Agents == null || roster == null || roster.Count < 2)
            {
                return;
            }

            ResolveRivalPair(roster, out LocalPersona left, out LocalPersona right);
            // Only script the named rivals (涨价风波); fallback pairs keep sine mood.
            if (left == null || right == null
                || left.AgentId != RivalLeftId || right.AgentId != RivalRightId
                || !snapshot.Agents.TryGetValue(left.AgentId, out SimAgentState leftState)
                || !snapshot.Agents.TryGetValue(right.AgentId, out SimAgentState rightState))
            {
                return;
            }

            double seedLeft = RelationSeed(left, right.AgentId);
            double seedRight = RelationSeed(right, left.AgentId);
            double delta = RivalRelationDelta(tick);
            leftState.Relationships[right.AgentId] = ClampRelation(seedLeft + delta);
            rightState.Relationships[left.AgentId] = ClampRelation(seedRight + delta);

            double moodBias = RivalMoodBias(tick);
            leftState.Mood = ClampMood(leftState.Mood + moodBias);
            rightState.Mood = ClampMood(rightState.Mood + moodBias);
        }

        /// <summary>Festival pack: rivals thaw toward square gather / celebration.</summary>
        private static void ApplyFestivalArc(
            SimTickSnapshot snapshot, List<LocalPersona> roster, int tick)
        {
            if (snapshot?.Agents == null || roster == null || roster.Count < 2)
            {
                return;
            }

            ResolveRivalPair(roster, out LocalPersona left, out LocalPersona right);
            if (left == null || right == null
                || !snapshot.Agents.TryGetValue(left.AgentId, out SimAgentState leftState)
                || !snapshot.Agents.TryGetValue(right.AgentId, out SimAgentState rightState))
            {
                return;
            }

            double seedLeft = RelationSeed(left, right.AgentId);
            double seedRight = RelationSeed(right, left.AgentId);
            double delta = 0.0;
            if (tick >= 3) delta += 0.08;
            if (tick >= 6) delta += 0.10;
            if (tick >= 9) delta += 0.12;
            if (tick >= 12) delta += 0.10;
            if (tick >= 15) delta += 0.14;
            if (tick >= 18) delta += 0.10;
            leftState.Relationships[right.AgentId] = ClampRelation(seedLeft + delta);
            rightState.Relationships[left.AgentId] = ClampRelation(seedRight + delta);

            double moodBias = tick >= 15 ? 0.28 : tick >= 9 ? 0.18 : tick >= 6 ? 0.12 : 0.06;
            leftState.Mood = ClampMood(leftState.Mood + moodBias);
            rightState.Mood = ClampMood(rightState.Mood + moodBias);
        }

        /// <summary>Town-hall pack: mild tension → vote → relief.</summary>
        private static void ApplyTownHallArc(
            SimTickSnapshot snapshot, List<LocalPersona> roster, int tick)
        {
            if (snapshot?.Agents == null || roster == null || roster.Count < 2)
            {
                return;
            }

            ResolveRivalPair(roster, out LocalPersona left, out LocalPersona right);
            if (left == null || right == null
                || !snapshot.Agents.TryGetValue(left.AgentId, out SimAgentState leftState)
                || !snapshot.Agents.TryGetValue(right.AgentId, out SimAgentState rightState))
            {
                return;
            }

            double seedLeft = RelationSeed(left, right.AgentId);
            double seedRight = RelationSeed(right, left.AgentId);
            double delta = 0.0;
            if (tick >= 3) delta -= 0.06;
            if (tick >= 6) delta -= 0.08;
            if (tick >= 9) delta += 0.10;  // debate softens
            if (tick >= 12) delta += 0.16; // vote passes
            if (tick >= 15) delta += 0.12;
            if (tick >= 18) delta += 0.10;
            leftState.Relationships[right.AgentId] = ClampRelation(seedLeft + delta);
            rightState.Relationships[left.AgentId] = ClampRelation(seedRight + delta);

            double moodBias = tick >= 15 ? 0.16 : tick >= 12 ? 0.10 : tick >= 9 ? 0.02 : -0.08;
            leftState.Mood = ClampMood(leftState.Mood + moodBias);
            rightState.Mood = ClampMood(rightState.Mood + moodBias);
        }

        private static Dictionary<string, double> SeedRelationships(LocalPersona persona)
        {
            var copy = new Dictionary<string, double>();
            if (persona?.Relationships == null)
            {
                return copy;
            }

            foreach (KeyValuePair<string, double> pair in persona.Relationships)
            {
                copy[pair.Key] = pair.Value;
            }

            return copy;
        }

        private static double RelationSeed(LocalPersona persona, string otherId)
        {
            if (persona?.Relationships != null
                && persona.Relationships.TryGetValue(otherId, out double value))
            {
                return value;
            }

            return -0.4;
        }

        /// <summary>
        /// Cumulative delta vs persona seed. Tick≥9 (爆发) is the trough;
        /// tick≥24 (和解) / ≥27 (巩固) recovers.
        /// Aligned with backend scripted.py nine-beat arc.
        /// </summary>
        private static double RivalRelationDelta(int tick)
        {
            double delta = 0.0;
            if (tick >= 3) delta -= 0.12; // 试探
            if (tick >= 6) delta -= 0.10; // 趁乱
            if (tick >= 9) delta -= 0.22; // 爆发 — trough
            if (tick >= 12) delta += 0.06; // 避险 — slight thaw
            if (tick >= 15) delta += 0.20; // 调解 (Liu)
            if (tick >= 18) delta += 0.10; // 表决
            if (tick >= 21) delta += 0.12; // 收场
            if (tick >= 24) delta += 0.22; // 和解
            if (tick >= 27) delta += 0.14; // 巩固
            return delta;
        }

        private static double RivalMoodBias(int tick)
        {
            if (tick >= 27) return 0.22;  // 巩固
            if (tick >= 24) return 0.18;  // 和解
            if (tick >= 21) return 0.10;  // 收场
            if (tick >= 18) return 0.06;  // 表决
            if (tick >= 15) return 0.05;  // 调解
            if (tick >= 12) return -0.20; // 避险 / storm
            if (tick >= 9) return -0.35;  // 爆发 trough
            if (tick >= 6) return -0.18;  // 趁乱
            if (tick >= 3) return -0.08;  // 试探
            return 0.0;
        }

        private static double ClampRelation(double value) =>
            Math.Max(-1.0, Math.Min(1.0, value));

        private static double ClampMood(double value) =>
            Math.Max(-1.0, Math.Min(1.0, value));

        // Aligned with backend scripted.py: interaction every 3 ticks,
        // world_event every 6 ticks. Nine-beat arc includes Liu mediation + vote.
        // Story: 试探→趁乱→爆发→避险→调解→表决→收场→和解→巩固;
        // world_event 序 price_surge→storm→festival.
        private const int DemoPulseInterval = 3;
        private const int DemoWorldEventInterval = 6;
        private const string RivalLeftId = "zhao";
        private const string RivalRightId = "wang";
        private const string MediatorId = "liu";

        private static readonly string[] DemoWorldPresets =
        {
            "price_surge", "storm", "festival",
        };

        private static readonly string[] FestivalWorldPresets =
        {
            "festival", "festival", "festival",
        };

        private static readonly string[] TownHallWorldPresets =
        {
            "announcement", "festival", "festival",
        };

        private sealed class StoryBeat
        {
            public string Kind; // conversation | trade | vote
            public string ArcLabel; // e.g. 涨价风波·试探
            public (string Speaker, string Text)[] Lines; // Speaker = "a" | "b" | "m"
            public string TradeItem;
            public int TradeQty;
            public double TradePrice;
            public string WorldBlurb; // optional description when this beat coincides with world_event
            public string Narration; // transition / narration between or on beats
            public string VoteMotion;
            /// <summary>Optional gather region for overlay visibility (图书馆 / 工坊 / 码头…).</summary>
            public string Location;
        }

        private static StoryBeat[] BeatsFor(string packId)
        {
            string id = DemoPackIds.Normalize(packId);
            if (DemoStoryPackCatalog.TryGet(id, out DemoStoryPackDef def)
                && def.Beats != null
                && def.Beats.Length > 0)
            {
                StoryBeat[] fromJson = MapBeats(def.Beats);
                if (fromJson != null && fromJson.Length > 0)
                {
                    return fromJson;
                }
            }

            // Fallback when JSON SoT missing / unreadable (runtime). EditMode asserts JSON loads.
            return id switch
            {
                DemoPackIds.Festival => FestivalStoryBeats,
                DemoPackIds.TownHall => TownHallStoryBeats,
                _ => PriceSurgeStoryBeats,
            };
        }

        private static string[] WorldPresetsFor(string packId)
        {
            string id = DemoPackIds.Normalize(packId);
            if (DemoStoryPackCatalog.TryGet(id, out DemoStoryPackDef def)
                && def.WorldPresets != null
                && def.WorldPresets.Length > 0)
            {
                return def.WorldPresets;
            }

            return id switch
            {
                DemoPackIds.Festival => FestivalWorldPresets,
                DemoPackIds.TownHall => TownHallWorldPresets,
                _ => DemoWorldPresets,
            };
        }

        private static StoryBeat[] MapBeats(DemoStoryBeatDef[] defs)
        {
            if (defs == null || defs.Length == 0)
            {
                return Array.Empty<StoryBeat>();
            }

            var beats = new StoryBeat[defs.Length];
            for (int i = 0; i < defs.Length; i++)
            {
                DemoStoryBeatDef d = defs[i];
                var beat = new StoryBeat
                {
                    Kind = d?.Kind ?? "conversation",
                    ArcLabel = d?.ArcLabel ?? "",
                    WorldBlurb = d?.WorldBlurb,
                    Narration = d?.ResolvedNarration,
                    VoteMotion = d?.VoteMotion,
                    Location = d?.Location,
                };

                if (d?.Trade != null)
                {
                    beat.TradeItem = d.Trade.Item;
                    beat.TradeQty = d.Trade.Qty;
                    beat.TradePrice = d.Trade.BasePrice;
                }

                if (d?.Lines != null && d.Lines.Length > 0)
                {
                    beat.Lines = new (string Speaker, string Text)[d.Lines.Length];
                    for (int j = 0; j < d.Lines.Length; j++)
                    {
                        DemoStoryLineDef line = d.Lines[j];
                        beat.Lines[j] = (
                            string.IsNullOrEmpty(line?.Speaker) ? "a" : line.Speaker,
                            line?.Text ?? "");
                    }
                }
                else
                {
                    beat.Lines = Array.Empty<(string, string)>();
                }

                beats[i] = beat;
            }

            return beats;
        }

        // Embedded fallback only — Offline SoT is Fixtures/demo-story-packs.json.
        // Fallback when StreamingAssets JSON missing / unreadable (runtime).
        // EditMode asserts JSON loads. Canonical SoT: packages/town-story-packs
        // → pnpm gen:story-packs. Do not rewrite story copy here.
        private static readonly StoryBeat[] PriceSurgeStoryBeats =
        {
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "涨价风波·试探",
                Lines = new[]
                {
                    ("a", "王婶，听说你今早进的青菜比我便宜两成？这价是从哪来的？"),
                    ("b", "赵老板少打听！我的老主顾等着要货，你管得着吗？"),
                    ("a", "市场就这么大，别怪我回头压价——咱们走着瞧。"),
                },
            },
            new StoryBeat
            {
                Kind = "trade",
                ArcLabel = "涨价风波·趁乱",
                Lines = new[]
                {
                    ("a", "进货渠道都紧了，这批日用品我按市价收——你别跟我扯旧账。"),
                    ("b", "市价？你分明趁乱加码！……行，先成交，账以后再算。"),
                    ("a", "成交。涨价风一来，谁先囤谁活——你懂的。"),
                },
                TradeItem = "日用品",
                TradeQty = 1,
                TradePrice = 12,
                WorldBlurb = "赵老板与王婶的进货渠道同时告急，日用品与青菜价格飙升，市场人心浮动。",
            },
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "涨价风波·爆发",
                Location = "图书馆",
                Lines = new[]
                {
                    ("b", "赵老板！你昨儿那笔日用品明明吃了涨价的红利，还到处说是我哄抬？"),
                    ("a", "我只是跟行情走。你自己进货不稳，别往我身上泼脏水。"),
                    ("b", "行情？我看是你故意放风！再这样我连你摊位都不让过。"),
                    ("a", "随你。反正镇民认的是货，不是嗓门。"),
                },
            },
            new StoryBeat
            {
                Kind = "trade",
                ArcLabel = "涨价风波·避险",
                Location = "码头",
                Lines = new[]
                {
                    ("a", "暴风雨要来了，我缺防水布——你那儿还有存货吗？按现价，少废话。"),
                    ("b", "……有。暴风雨里谁都别想赚痛快钱，拿去，别再扯进货的事。"),
                    ("a", "成交。雨停了咱们再算旧账。"),
                },
                TradeItem = "防水布",
                TradeQty = 1,
                TradePrice = 18,
                WorldBlurb = "乌云压镇，狂风暴雨将至；市场早早收摊，居民赶着囤避险物资。",
            },
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "涨价风波·调解",
                Lines = new[]
                {
                    ("m", "赵老板、王婶，再当街吵我就记警告。涨价的事，去镇政厅说清楚。"),
                    ("a", "……听见了，刘警官。我不是要闹事，是进货真紧。"),
                    ("b", "那行，各卖各的。涨价的事，等雨停了再跟镇政厅说清楚。"),
                    ("m", "好。今晚镇政厅有议题，你们都到场——用投票，别用嗓门。"),
                },
            },
            new StoryBeat
            {
                Kind = "vote",
                ArcLabel = "涨价风波·表决",
                VoteMotion = "是否临时限价并延长夜市开放时间？",
                Lines = new[]
                {
                    ("m", "议题宣读：是否临时限价并延长夜市，缓解涨价纠纷。请表决。"),
                    ("a", "支持限价——乱涨只会把市场吵散。"),
                    ("b", "……也支持。限价比互相泼脏水强。"),
                },
            },
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "涨价风波·收场",
                Lines = new[]
                {
                    ("m", "表决结果已经记档。赵老板、王婶，回去各守各的摊，别再当街对骂。"),
                    ("a", "知道了。限价我认——至少规矩清楚。"),
                    ("b", "我也认。刘警官，下次有事我们直接去镇政厅。"),
                },
            },
            new StoryBeat
            {
                Kind = "trade",
                ArcLabel = "涨价风波·和解",
                Lines = new[]
                {
                    ("a", "广场在办庆典，我缺点装饰用的彩带——按平价跟你换，算和解？"),
                    ("b", "……看在节日份上。平价就平价，别再提那阵涨价风。"),
                    ("a", "成交。今天镇上热闹，咱们也别扫兴。"),
                },
                TradeItem = "彩带",
                TradeQty = 2,
                TradePrice = 8,
                WorldBlurb = "广场张灯结彩，节日庆典拉开帷幕；市场恩怨暂搁一边，镇上气氛回暖。",
            },
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "涨价风波·巩固",
                Lines = new[]
                {
                    ("b", "赵老板，夜市限价后客流回来了——你那摊日用品也别再藏着掖着。"),
                    ("a", "行，货我正常出。王婶，青菜也别再卡我老主顾。"),
                    ("m", "这样就对了。有纠纷还是走镇政厅，别再让我跑第二趟。"),
                    ("a", "听见了。今天市场太平，比吵架强。"),
                },
            },
        };

        // Festival pack: gather → decorate → trade → celebrate → toast → linger (6 beats).
        private static readonly StoryBeat[] FestivalStoryBeats =
        {
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "节日庆典·邀约",
                Lines = new[]
                {
                    ("a", "王婶，广场今晚张灯——你摊上那批彩带借我用用？"),
                    ("b", "节日嘛，谁不乐意热闹。彩带你拿去，记得还。"),
                    ("a", "成。咱们市场的人也该去广场露个脸。"),
                },
            },
            new StoryBeat
            {
                Kind = "trade",
                ArcLabel = "节日庆典·备货",
                Lines = new[]
                {
                    ("a", "庆典要摆摊，我缺两卷彩带——平价跟你换。"),
                    ("b", "平价就平价，看在节日份上。拿去吧。"),
                    ("a", "成交。广场见。"),
                },
                TradeItem = "彩带",
                TradeQty = 2,
                TradePrice = 8,
                WorldBlurb = "广场张灯结彩，节日庆典拉开帷幕；镇民往广场聚集，气氛回暖。",
            },
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "节日庆典·聚集",
                Lines = new[]
                {
                    ("m", "各位，广场灯已点上。今晚别吵进货，先把庆典办好。"),
                    ("a", "听见了，刘警官。我把摊挪近广场。"),
                    ("b", "我也去。节日里吵价多没劲。"),
                },
            },
            new StoryBeat
            {
                Kind = "trade",
                ArcLabel = "节日庆典·互惠",
                Location = "工坊",
                Lines = new[]
                {
                    ("b", "赵老板，我缺几串灯笼——你那儿还有吗？"),
                    ("a", "有。节日价，不坑你。"),
                    ("b", "成交。今晚广场见。"),
                },
                TradeItem = "灯笼",
                TradeQty = 3,
                TradePrice = 6,
            },
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "节日庆典·干杯",
                Lines = new[]
                {
                    ("a", "王婶，彩带挂上了——今晚广场真热闹。"),
                    ("b", "是啊。涨价那阵子的气，今天先放下。"),
                    ("m", "这就对了。节日里和解，比任何公告都管用。"),
                    ("a", "干杯——为小镇。"),
                },
                WorldBlurb = "广场庆典进入高潮，灯火与笑语交织；市场恩怨暂搁一边。",
            },
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "节日庆典·余韵",
                Lines = new[]
                {
                    ("b", "灯还亮着。赵老板，明天市场照常——别再藏货。"),
                    ("a", "行。节日过了也别把气氛弄僵。"),
                    ("m", "散场吧。有事还是走镇政厅。"),
                },
            },
        };

        // Town-hall pack: notice → lobby → debate → vote → announce → settle (6 beats).
        private static readonly StoryBeat[] TownHallStoryBeats =
        {
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "镇政厅·公告",
                Lines = new[]
                {
                    ("m", "镇政厅贴了告示：下周是否举办镇民大会，今晚表决。"),
                    ("a", "终于要开会了？涨价那阵子就该开。"),
                    ("b", "开就开。别又变成吵架场。"),
                },
                WorldBlurb = "镇政厅张贴公告：今晚就「是否举办镇民大会」进行表决，请镇民到场。",
            },
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "镇政厅·游说",
                Location = "图书馆",
                Lines = new[]
                {
                    ("a", "王婶，你投赞成吧——大会能把限价规矩说清楚。"),
                    ("b", "我还在想。开会是好事，别变成你单方面压我。"),
                    ("a", "规矩对大家都好。晚上镇政厅见。"),
                },
            },
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "镇政厅·辩论",
                Lines = new[]
                {
                    ("m", "议题宣读前，双方各说一句。赵老板？"),
                    ("a", "赞成开会——市场纠纷需要公开规则。"),
                    ("b", "我也赞成，但要保证菜贩有发言席。"),
                    ("m", "记下了。请入座，准备表决。"),
                },
            },
            new StoryBeat
            {
                Kind = "vote",
                ArcLabel = "镇政厅·表决",
                VoteMotion = "是否下周举办镇民大会？",
                Lines = new[]
                {
                    ("m", "议题：是否下周举办镇民大会。请表决。"),
                    ("a", "支持——把规矩摆到台面上。"),
                    ("b", "支持。有席位我就投。"),
                },
                WorldBlurb = "镇政厅表决通过：下周举办镇民大会；广场将张灯迎接公开议事。",
            },
            new StoryBeat
            {
                Kind = "conversation",
                ArcLabel = "镇政厅·宣读",
                Lines = new[]
                {
                    ("m", "表决结果：通过。下周镇民大会正式排期。"),
                    ("a", "好。到时候限价、夜市都摊开说。"),
                    ("b", "行。刘警官，菜贩席位别忘了。"),
                },
            },
            new StoryBeat
            {
                Kind = "trade",
                ArcLabel = "镇政厅·落定",
                Lines = new[]
                {
                    ("a", "大会定了，我缺份告示纸——跟你换点？"),
                    ("b", "换。把「菜贩发言席」也写上。"),
                    ("a", "成交。下周镇政厅见。"),
                },
                TradeItem = "告示纸",
                TradeQty = 1,
                TradePrice = 4,
            },
        };

        private static void AddDemoInteractions(
            OfflineDemoPack pack,
            List<LocalPersona> roster,
            int tick,
            int hour,
            StoryBeat[] beats,
            string[] worldPresets)
        {
            if (roster.Count < 2 || beats == null || beats.Length == 0)
            {
                return;
            }

            ResolveRivalPair(roster, out LocalPersona left, out LocalPersona right);
            string a = left.AgentId;
            string b = right.AgentId;
            string aName = left.Name;
            string bName = right.Name;
            ResolveMediator(roster, out string m, out string mName);

            // Pulse cadence matches server SCRIPTED_DEMO_INTERVAL / WORLD_EVENT_INTERVAL.
            if (tick > 0 && tick % DemoPulseInterval == 0)
            {
                int pulseIndex = tick / DemoPulseInterval;
                StoryBeat beat = beats[(pulseIndex - 1) % beats.Length];
                if (beat.Kind == "conversation")
                {
                    AddConversationPulse(pack, tick, hour, beat, a, b, aName, bName, m, mName);
                }
                else if (beat.Kind == "vote")
                {
                    AddStoryVotePulse(pack, tick, hour, beat, a, b, aName, bName, m, mName);
                }
                else
                {
                    AddTradePulse(pack, tick, hour, beat, a, b, aName, bName);
                }
            }

            if (tick > 0 && tick % DemoWorldEventInterval == 0)
            {
                AddWorldEventPulse(pack, tick, hour, beats, worldPresets);
            }
        }

        private static void ResolveMediator(
            List<LocalPersona> roster, out string mediatorId, out string mediatorName)
        {
            foreach (LocalPersona p in roster)
            {
                if (p != null && p.AgentId == MediatorId)
                {
                    mediatorId = p.AgentId;
                    mediatorName = string.IsNullOrEmpty(p.Name) ? "刘警官" : p.Name;
                    return;
                }
            }

            mediatorId = MediatorId;
            mediatorName = "刘警官";
        }

        /// <summary>Prefer roster zhao/wang (涨价风波 rivals); else first two personas.</summary>
        private static void ResolveRivalPair(
            List<LocalPersona> roster, out LocalPersona left, out LocalPersona right)
        {
            LocalPersona zhao = null;
            LocalPersona wang = null;
            foreach (LocalPersona p in roster)
            {
                if (p == null)
                {
                    continue;
                }

                if (p.AgentId == RivalLeftId)
                {
                    zhao = p;
                }
                else if (p.AgentId == RivalRightId)
                {
                    wang = p;
                }
            }

            if (zhao != null && wang != null)
            {
                left = zhao;
                right = wang;
                return;
            }

            if (roster.Count < 2)
            {
                left = roster.Count > 0 ? roster[0] : null;
                right = null;
                return;
            }

            left = roster[0];
            right = roster[1];
        }

        private static List<InteractionTranscriptLine> BuildBeatTranscript(
            StoryBeat beat,
            string a,
            string b,
            string aName,
            string bName,
            string mediatorId = null,
            string mediatorName = null)
        {
            var lines = new List<InteractionTranscriptLine>();
            if (beat?.Lines == null)
            {
                return lines;
            }

            string mId = string.IsNullOrEmpty(mediatorId) ? MediatorId : mediatorId;
            string mName = string.IsNullOrEmpty(mediatorName) ? "刘警官" : mediatorName;

            for (int i = 0; i < beat.Lines.Length; i++)
            {
                (string speaker, string text) = beat.Lines[i];
                string speakerId;
                string speakerName;
                if (speaker == "m")
                {
                    speakerId = mId;
                    speakerName = mName;
                }
                else if (speaker == "b")
                {
                    speakerId = b;
                    speakerName = bName;
                }
                else
                {
                    speakerId = a;
                    speakerName = aName;
                }

                lines.Add(new InteractionTranscriptLine
                {
                    SpeakerId = speakerId,
                    SpeakerName = speakerName,
                    Text = text,
                    Round = i,
                });
            }

            return lines;
        }

        private static void AddConversationPulse(
            OfflineDemoPack pack,
            int tick,
            int hour,
            StoryBeat beat,
            string a,
            string b,
            string aName,
            string bName,
            string mediatorId,
            string mediatorName)
        {
            List<InteractionTranscriptLine> transcript = BuildBeatTranscript(
                beat, a, b, aName, bName, mediatorId, mediatorName);
            string summary = $"tick{tick} {aName}与{bName}（{beat.ArcLabel}）";
            var ix = new ActiveInteraction
            {
                Id = $"demo-conv-{tick}",
                Tick = tick,
                Kind = "conversation",
                Status = "completed",
                InitiatorId = a,
                TargetId = b,
                Summary = summary,
                Transcript = transcript,
                ExpiresAtRealtime = float.PositiveInfinity,
            };
            pack.Interactions.Add(ix);
            pack.Events.Add(new SimTickEvent
            {
                Tick = tick,
                Type = "sim.interaction",
                AgentId = a,
                Summary = ix.Summary,
                Detail = InteractionModel.FormatTranscript(transcript),
                Timestamp = $"2026-01-01T{hour:D2}:00:00.200Z",
            });
            pack.Decisions.Add(new SimDecision
            {
                Tick = tick,
                AgentId = a,
                Summary = ix.Summary,
                ActionType = "conversation",
            });
        }

        private static void AddTradePulse(
            OfflineDemoPack pack,
            int tick,
            int hour,
            StoryBeat beat,
            string a,
            string b,
            string aName,
            string bName)
        {
            string item = string.IsNullOrEmpty(beat.TradeItem) ? "日用品" : beat.TradeItem;
            int qty = beat.TradeQty > 0 ? beat.TradeQty : 1;
            double price = beat.TradePrice > 0 ? beat.TradePrice : 10;
            List<InteractionTranscriptLine> transcript = BuildBeatTranscript(beat, a, b, aName, bName);
            string summary =
                $"tick{tick} 成交：{aName}←{bName} {item}×{qty} @{price:0}币（{beat.ArcLabel}）";
            var ix = new ActiveInteraction
            {
                Id = $"demo-trade-{tick}",
                Tick = tick,
                Kind = "trade",
                Status = "completed",
                InitiatorId = a,
                TargetId = b,
                Summary = summary,
                Transcript = transcript,
                StateChanges = new InteractionStateChanges
                {
                    InventoryTransfers = new List<JObject>
                    {
                        new() { ["item"] = item, ["quantity"] = qty },
                    },
                    MoneyTransfers = new List<JObject>
                    {
                        new() { ["amount"] = price },
                    },
                },
                ExpiresAtRealtime = float.PositiveInfinity,
            };
            pack.Interactions.Add(ix);
            pack.Events.Add(new SimTickEvent
            {
                Tick = tick,
                Type = "sim.interaction",
                AgentId = a,
                Summary = ix.Summary,
                Detail = InteractionModel.FormatTranscript(transcript),
                Timestamp = $"2026-01-01T{hour:D2}:00:00.300Z",
            });
            pack.Decisions.Add(new SimDecision
            {
                Tick = tick,
                AgentId = a,
                Summary = ix.Summary,
                ActionType = "trade",
            });
        }

        private static void AddWorldEventPulse(
            OfflineDemoPack pack, int tick, int hour, StoryBeat[] beats, string[] worldPresets)
        {
            if (worldPresets == null || worldPresets.Length == 0)
            {
                return;
            }

            int idx = (tick / DemoWorldEventInterval - 1) % worldPresets.Length;
            string preset = worldPresets[idx];
            string title = preset switch
            {
                "festival" => "节日庆典",
                "price_surge" => "市场物价上涨",
                "storm" => "暴风雨来袭",
                "announcement" => "镇政厅公告",
                _ => preset,
            };
            // Prefer story blurb only when it matches this preset (same as backend).
            string detail = "";
            int pulseIndex = tick / DemoPulseInterval;
            if (pulseIndex > 0 && beats != null && beats.Length > 0)
            {
                StoryBeat beat = beats[(pulseIndex - 1) % beats.Length];
                if (!string.IsNullOrEmpty(beat.WorldBlurb)
                    && BlurbMatchesPreset(beat.WorldBlurb, preset))
                {
                    detail = beat.WorldBlurb;
                }
                else if (!string.IsNullOrEmpty(beat.Narration)
                    && BlurbMatchesPreset(beat.Narration, preset))
                {
                    detail = beat.Narration;
                }
                else if (!string.IsNullOrEmpty(beat.WorldBlurb))
                {
                    detail = beat.WorldBlurb;
                }
                else if (!string.IsNullOrEmpty(beat.Narration))
                {
                    detail = beat.Narration;
                }
            }

            pack.Events.Add(new SimTickEvent
            {
                Tick = tick,
                Type = "sim.world_event",
                AgentId = "",
                Summary = title,
                Detail = detail,
                Timestamp = $"2026-01-01T{hour:D2}:00:00.150Z",
            });
        }

        private static bool BlurbMatchesPreset(string blurb, string preset)
        {
            if (string.IsNullOrEmpty(blurb) || string.IsNullOrEmpty(preset))
            {
                return false;
            }

            return preset switch
            {
                "price_surge" => blurb.Contains("价格") || blurb.Contains("涨价") || blurb.Contains("物价"),
                "storm" => blurb.Contains("暴风") || blurb.Contains("雨") || blurb.Contains("避险"),
                "festival" => blurb.Contains("节日") || blurb.Contains("庆典") || blurb.Contains("广场张灯"),
                "announcement" => blurb.Contains("公告") || blurb.Contains("镇政厅") || blurb.Contains("表决"),
                _ => false,
            };
        }

        private static void AddStoryVotePulse(
            OfflineDemoPack pack,
            int tick,
            int hour,
            StoryBeat beat,
            string a,
            string b,
            string aName,
            string bName,
            string mediatorId,
            string mediatorName)
        {
            string motion = string.IsNullOrEmpty(beat.VoteMotion)
                ? "是否临时限价并延长夜市开放时间？"
                : beat.VoteMotion;
            List<InteractionTranscriptLine> transcript = BuildBeatTranscript(
                beat, a, b, aName, bName, mediatorId, mediatorName);
            string summary =
                $"tick{tick} 投票「{motion}」→ 通过 (支持5/反对1/弃权1)（{beat.ArcLabel}）";
            string initiator = string.IsNullOrEmpty(mediatorId) ? a : mediatorId;
            var ix = new ActiveInteraction
            {
                Id = $"demo-vote-{tick}",
                Tick = tick,
                Kind = "vote",
                Status = "completed",
                InitiatorId = initiator,
                TargetId = null,
                Summary = summary,
                Transcript = transcript,
                StateChanges = new InteractionStateChanges
                {
                    Governance = new JObject
                    {
                        ["motion"] = motion,
                        ["outcome"] = "通过",
                        ["yes"] = 5,
                        ["no"] = 1,
                        ["abstain"] = 1,
                    },
                },
                ExpiresAtRealtime = float.PositiveInfinity,
            };
            pack.Interactions.Add(ix);
            pack.Events.Add(new SimTickEvent
            {
                Tick = tick,
                Type = "sim.interaction",
                AgentId = initiator,
                Summary = ix.Summary,
                Detail = InteractionModel.FormatTranscript(transcript),
                Timestamp = $"2026-01-01T{hour:D2}:00:00.400Z",
            });
            pack.Decisions.Add(new SimDecision
            {
                Tick = tick,
                AgentId = initiator,
                Summary = ix.Summary,
                ActionType = "vote",
            });
        }

        private static List<LocalPersona> ResolveRoster(IReadOnlyList<LocalPersona> personas)
        {
            var roster = new List<LocalPersona>();
            if (personas != null)
            {
                foreach (LocalPersona p in personas)
                {
                    if (p != null && !string.IsNullOrEmpty(p.AgentId))
                    {
                        roster.Add(p);
                    }
                }
            }

            if (roster.Count > 0)
            {
                return roster;
            }

            return new List<LocalPersona>
            {
                new LocalPersona
                {
                    AgentId = "lin",
                    Name = "林小梅",
                    Role = "面包师",
                    Home = "面包店",
                    Goal = "今天多卖二十个可颂",
                },
                new LocalPersona
                {
                    AgentId = "chen",
                    Name = "陈大爷",
                    Role = "退休教师",
                    Home = "公园",
                    Goal = "在公园晒太阳",
                },
            };
        }

        private static Dictionary<string, WireVec3> ResolveAnchors(IReadOnlyDictionary<string, WireVec3> regions)
        {
            var anchors = new Dictionary<string, WireVec3>();
            if (regions != null)
            {
                foreach (KeyValuePair<string, WireVec3> pair in regions)
                {
                    anchors[pair.Key] = pair.Value;
                }
            }

            if (anchors.Count == 0)
            {
                anchors["广场"] = new WireVec3(0, 0, 0);
                anchors["市场"] = new WireVec3(36, 0, 0);
                anchors["餐厅"] = new WireVec3(52, 0, 20);
                anchors["面包店"] = new WireVec3(36, 0, -22);
                anchors["住宅区"] = new WireVec3(18, 0, 38);
                anchors["镇政厅"] = new WireVec3(-22, 0, -20);
                anchors["公园"] = new WireVec3(-32, 0, 12);
                anchors["图书馆"] = new WireVec3(-40, 0, -8);
                anchors["工坊"] = new WireVec3(48, 0, -36);
                anchors["码头"] = new WireVec3(-8, 0, 40);
                anchors["心动营地"] = new WireVec3(-56, 0, 36);
            }

            return anchors;
        }

        /// <summary>
        /// On story-pulse ticks, move rivals (+ mediator when present in lines) to
        /// <see cref="StoryBeat.Location"/> so conversation/trade overlays appear in
        /// 图书馆 / 工坊 / 码头 (and other named districts).
        /// </summary>
        private static void GatherForStoryPulse(
            SimTickSnapshot snapshot,
            List<LocalPersona> roster,
            int tick,
            StoryBeat[] beats,
            IReadOnlyDictionary<string, WireVec3> anchors)
        {
            if (snapshot?.Agents == null
                || roster == null
                || beats == null
                || beats.Length == 0
                || tick <= 0
                || tick % DemoPulseInterval != 0)
            {
                return;
            }

            int pulseIndex = tick / DemoPulseInterval;
            StoryBeat beat = beats[(pulseIndex - 1) % beats.Length];
            string region = string.IsNullOrEmpty(beat.Location) ? null : beat.Location;
            if (string.IsNullOrEmpty(region) || !anchors.ContainsKey(region))
            {
                // Votes default to 镇政厅 when no explicit location.
                if (beat.Kind == "vote" && anchors.ContainsKey("镇政厅"))
                {
                    region = "镇政厅";
                }
                else
                {
                    return;
                }
            }

            ResolveRivalPair(roster, out LocalPersona left, out LocalPersona right);
            ResolveMediator(roster, out string mediatorId, out _);
            bool needMediator = beat.Lines != null
                && Array.Exists(beat.Lines, line => line.Speaker == "m");

            PlaceAgentAtRegion(snapshot, left?.AgentId, region, anchors, 0);
            PlaceAgentAtRegion(snapshot, right?.AgentId, region, anchors, 1);
            if (needMediator)
            {
                PlaceAgentAtRegion(snapshot, mediatorId, region, anchors, 2);
            }
        }

        private static void PlaceAgentAtRegion(
            SimTickSnapshot snapshot,
            string agentId,
            string region,
            IReadOnlyDictionary<string, WireVec3> anchors,
            int slot)
        {
            if (string.IsNullOrEmpty(agentId)
                || snapshot.Agents == null
                || !snapshot.Agents.TryGetValue(agentId, out SimAgentState agent)
                || !anchors.TryGetValue(region, out WireVec3 wire))
            {
                return;
            }

            double ox = (slot - 1) * 1.4;
            double oz = slot == 1 ? 0.8 : -0.6;
            agent.Location = region;
            agent.Position = new WireVec3(wire.X + ox, wire.Y, wire.Z + oz);
            agent.Activity = "交谈";
        }

        private static RunManifest BuildManifest(
            IReadOnlyList<LocalPersona> roster,
            IReadOnlyDictionary<string, WireVec3> anchors,
            string packId = null)
        {
            string resolved = DemoPackIds.Normalize(packId);
            var manifest = new RunManifest
            {
                ManifestVersion = $"offline-demo:{resolved}",
                Scenario = "town",
                Seed = 42,
                Personas = new List<SimPersona>(),
                Regions = new List<string>(anchors.Keys),
            };

            foreach (LocalPersona p in roster)
            {
                manifest.Personas.Add(new SimPersona
                {
                    AgentId = p.AgentId,
                    Name = p.Name,
                    Role = p.Role,
                    Location = p.Home,
                    Goal = p.Goal ?? "",
                    BigFive = p.BigFive ?? new BigFive(),
                });
            }

            return manifest;
        }

        private static string LocationFor(
            LocalPersona persona,
            int index,
            int tick,
            IReadOnlyDictionary<string, WireVec3> anchors)
        {
            if (tick <= 1)
            {
                string home = string.IsNullOrEmpty(persona.Home) ? "广场" : persona.Home;
                return anchors.ContainsKey(home) ? home : FirstAnchor(anchors);
            }

            // Staggered tour so residents fan out across regions over time.
            int stopIndex = (index * 2 + tick - 1) % TourStops.Length;
            string stop = TourStops[stopIndex];
            return anchors.ContainsKey(stop) ? stop : FirstAnchor(anchors);
        }

        private static WireVec3 PositionFor(
            LocalPersona persona,
            string location,
            IReadOnlyDictionary<string, WireVec3> anchors,
            int tick,
            int index)
        {
            WireVec3 basePos = anchors.TryGetValue(location, out WireVec3 wire)
                ? wire
                : anchors.TryGetValue(persona.Home ?? "", out WireVec3 home)
                    ? home
                    : FirstWire(anchors);

            double ox = persona.SpawnOffset?.X ?? 0.0;
            double oz = persona.SpawnOffset?.Z ?? 0.0;
            // Small per-tick drift so Demo playback shows visible displacement.
            double driftX = Math.Sin((tick + index) * 0.55) * 1.2;
            double driftZ = Math.Cos((tick + index) * 0.4) * 1.0;
            return new WireVec3(basePos.X + ox + driftX, basePos.Y, basePos.Z + oz + driftZ);
        }

        private static string FirstAnchor(IReadOnlyDictionary<string, WireVec3> anchors)
        {
            foreach (string key in anchors.Keys)
            {
                return key;
            }

            return "广场";
        }

        private static WireVec3 FirstWire(IReadOnlyDictionary<string, WireVec3> anchors)
        {
            foreach (WireVec3 value in anchors.Values)
            {
                return value;
            }

            return new WireVec3(0, 0, 0);
        }
    }
}
