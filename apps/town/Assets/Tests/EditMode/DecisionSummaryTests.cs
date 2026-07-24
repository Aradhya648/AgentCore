using System.Collections.Generic;
using System.Linq;
using AgentTown.Simulation;
using AgentTown.Town;
using NUnit.Framework;

namespace AgentTown.Tests
{
    public sealed class DecisionSummaryTests
    {
        [Test]
        public void FormatPrimaryLine_PreferNameActionReason()
        {
            TownPersonas.PopulateForTests(new List<LocalPersona>
            {
                new LocalPersona { AgentId = "lin", Name = "林小梅", Home = "面包店" },
            });

            var decision = new SimDecision
            {
                Tick = 2,
                AgentId = "lin",
                ActionType = "move_to",
                Location = "市场",
                Summary = "赶路",
            };

            string line = DecisionSummary.FormatPrimaryLine(decision, session: null);
            Assert.AreEqual("林小梅 · 前往市场 · 赶路", line);
            Assert.AreEqual("T2 · move_to", DecisionSummary.FormatMetaLine(decision));
        }

        [Test]
        public void FormatPrimaryLine_FallsBackWithoutFabricating()
        {
            TownPersonas.PopulateForTests(new List<LocalPersona>());

            var decision = new SimDecision
            {
                Tick = 4,
                AgentId = "unknown-agent",
                ActionType = "",
                Location = "",
                Summary = "先把订单送完。",
            };

            string line = DecisionSummary.FormatPrimaryLine(decision, session: null);
            Assert.AreEqual("unknown-agent · 先把订单送完。", line);
        }

        [Test]
        public void OfflineDemo_Decisions_AreReadable()
        {
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
                    AgentId = "zhao",
                    Name = "赵老板",
                    Role = "杂货商",
                    Home = "市场",
                },
                new LocalPersona
                {
                    AgentId = "wang",
                    Name = "王婶",
                    Role = "菜贩",
                    Home = "市场",
                },
            };
            var regions = new Dictionary<string, WireVec3>
            {
                ["广场"] = new WireVec3(0, 0, 0),
                ["市场"] = new WireVec3(36, 0, 0),
                ["面包店"] = new WireVec3(36, 0, -22),
            };

            TownPersonas.PopulateForTests(personas);
            OfflineDemoPack pack = OfflineDemoBuilder.Build(personas, regions, frameCount: 12);
            Assert.GreaterOrEqual(pack.Decisions.Count, 1);

            SimDecision first = pack.Decisions[pack.Decisions.Count - 1];
            string line = DecisionSummary.FormatPrimaryLine(first, session: null);
            Assert.IsFalse(string.IsNullOrEmpty(line));
            Assert.IsFalse(line.StartsWith("{"), "must not dump JSON");

            SimDecision story = pack.Decisions.Find(d =>
                d != null && (d.ActionType == "conversation" || (d.Summary ?? "").Contains("涨价风波")));
            Assert.IsNotNull(story, "offline pack should include story decisions");
            string storyLine = DecisionSummary.FormatPrimaryLine(story, session: null);
            Assert.IsTrue(
                storyLine.Contains("涨价风波") || storyLine.Contains("对话") || storyLine.Contains("赵"),
                storyLine);
        }

        [Test]
        public void StoryDecisionScore_RanksConversationAboveMove()
        {
            var talk = new SimDecision { ActionType = "conversation", Summary = "涨价风波：摊位争执" };
            var move = new SimDecision { ActionType = "move_to", Summary = "闲逛" };

            Assert.Greater(DecisionSummary.StoryDecisionScore(talk), DecisionSummary.StoryDecisionScore(move));
            Assert.IsTrue(DecisionSummary.IsMoveNoise(move));
            Assert.IsFalse(DecisionSummary.IsMoveNoise(talk));
            Assert.IsTrue(DecisionSummary.LooksLikeStorySummary(talk.Summary));
        }

        [Test]
        public void BuildTabRows_SameTick_ConversationBeforeMove_AndCollapsesNoise()
        {
            var decisions = new List<SimDecision>
            {
                new SimDecision
                {
                    Tick = 8,
                    AgentId = "lin",
                    ActionType = "move_to",
                    Location = "市场",
                    Summary = "闲逛",
                },
                new SimDecision
                {
                    Tick = 8,
                    AgentId = "zhao",
                    ActionType = "conversation",
                    Location = "市场",
                    Summary = "涨价风波：青菜进货谈不拢",
                },
                new SimDecision
                {
                    Tick = 8,
                    AgentId = "wang",
                    ActionType = "move_to",
                    Location = "广场",
                    Summary = "赶路",
                },
                new SimDecision
                {
                    Tick = 8,
                    AgentId = "chen",
                    ActionType = "move_to",
                    Location = "公园",
                    Summary = "闲逛",
                },
            };

            List<DecisionTabRow> rows = DecisionSummary.BuildTabRows(decisions, maxRows: 20);

            Assert.IsTrue(rows[0].IsGroupHeader);
            Assert.IsTrue(rows[0].Text.StartsWith("T8"));
            Assert.IsTrue(rows[0].Text.Contains("涨价风波") || rows[0].Text.Contains("对话"), rows[0].Text);

            DecisionTabRow firstBody = rows.First(r => !r.IsGroupHeader && !r.IsCollapsedMoves);
            Assert.AreEqual("conversation", firstBody.Decision.ActionType);

            // Individual move_to rows must not appear when story is present.
            Assert.IsFalse(rows.Any(r =>
                !r.IsGroupHeader
                && !r.IsCollapsedMoves
                && r.Decision != null
                && DecisionSummary.IsMoveNoise(r.Decision)));

            DecisionTabRow collapsed = rows.FirstOrDefault(r => r.IsCollapsedMoves);
            Assert.IsNotNull(collapsed);
            Assert.IsTrue(collapsed.Text.Contains("次移动"), collapsed.Text);
            Assert.IsTrue(collapsed.Text.StartsWith("3"), collapsed.Text);
        }

        [Test]
        public void BuildTabRows_StoryTicks_DoNotFillTopWithMoveNoise()
        {
            var decisions = new List<SimDecision>
            {
                new SimDecision { Tick = 1, AgentId = "a", ActionType = "move_to", Summary = "闲逛" },
                new SimDecision { Tick = 1, AgentId = "b", ActionType = "move_to", Summary = "闲逛" },
                new SimDecision { Tick = 1, AgentId = "c", ActionType = "move_to", Summary = "闲逛" },
                new SimDecision { Tick = 1, AgentId = "d", ActionType = "move_to", Summary = "闲逛" },
                new SimDecision
                {
                    Tick = 9,
                    AgentId = "zhao",
                    ActionType = "conversation",
                    Summary = "涨价风波：摊位争执",
                },
                new SimDecision { Tick = 9, AgentId = "lin", ActionType = "move_to", Summary = "闲逛" },
                new SimDecision
                {
                    Tick = 12,
                    AgentId = "liu",
                    ActionType = "vote",
                    Summary = "限价表决",
                },
            };

            List<DecisionTabRow> rows = DecisionSummary.BuildTabRows(decisions, maxRows: 12);

            // First non-header body should be story (conversation or vote), not a move.
            DecisionTabRow firstBody = rows.First(r => !r.IsGroupHeader && !r.IsCollapsedMoves);
            Assert.IsFalse(DecisionSummary.IsMoveNoise(firstBody.Decision), firstBody.Decision.ActionType);
            Assert.Greater(DecisionSummary.StoryDecisionScore(firstBody.Decision), 0);

            int moveBodiesInTop = rows
                .Take(6)
                .Count(r => !r.IsGroupHeader && !r.IsCollapsedMoves
                    && r.Decision != null
                    && DecisionSummary.IsMoveNoise(r.Decision));
            Assert.LessOrEqual(moveBodiesInTop, 1, "story ticks should keep move noise out of the top rows");
        }

        [Test]
        public void BuildTabRows_IdleTick_StillShowsSomeMoves()
        {
            var decisions = new List<SimDecision>
            {
                new SimDecision { Tick = 2, AgentId = "a", ActionType = "move_to", Summary = "闲逛" },
                new SimDecision { Tick = 2, AgentId = "b", ActionType = "move_to", Summary = "闲逛" },
                new SimDecision { Tick = 2, AgentId = "c", ActionType = "move_to", Summary = "闲逛" },
                new SimDecision { Tick = 2, AgentId = "d", ActionType = "move_to", Summary = "闲逛" },
            };

            List<DecisionTabRow> rows = DecisionSummary.BuildTabRows(decisions, maxRows: 20);
            int moveBodies = rows.Count(r =>
                !r.IsGroupHeader && !r.IsCollapsedMoves && r.Decision != null);
            Assert.Greater(moveBodies, 0, "idle tick must not be empty");
            Assert.LessOrEqual(moveBodies, 3);
            Assert.IsTrue(rows.Any(r => r.IsCollapsedMoves));
        }
    }

    public sealed class AgentDisplayLabelsTests
    {
        [Test]
        public void MoodLabel_MatchesSharedThresholds()
        {
            Assert.AreEqual("愉快", AgentDisplayLabels.MoodLabel(0.6));
            Assert.AreEqual("平静", AgentDisplayLabels.MoodLabel(0.2));
            Assert.AreEqual("一般", AgentDisplayLabels.MoodLabel(0.0));
            Assert.AreEqual("低落", AgentDisplayLabels.MoodLabel(-0.3));
            Assert.AreEqual("沮丧", AgentDisplayLabels.MoodLabel(-0.8));
        }

        [Test]
        public void FormatNameplateSubtitle_RoleAndMood()
        {
            string line = AgentDisplayLabels.FormatNameplateSubtitle(
                "杂货商",
                includeMood: true,
                mood: 0.2);
            Assert.AreEqual("杂货商 · 平静", line);
        }

        [Test]
        public void FormatNameplateSubtitle_DegradesWhenFieldsMissing()
        {
            Assert.AreEqual(
                "杂货商",
                AgentDisplayLabels.FormatNameplateSubtitle("杂货商", includeMood: false, mood: 0));
            Assert.AreEqual(
                "平静",
                AgentDisplayLabels.FormatNameplateSubtitle("", includeMood: true, mood: 0.2));
            Assert.AreEqual(
                "赶路去市场…",
                AgentDisplayLabels.FormatNameplateSubtitle(
                    "",
                    includeMood: false,
                    mood: 0,
                    activityFallback: "赶路去市场买面粉和鸡蛋",
                    maxActivityChars: 6));
        }

        [Test]
        public void FormatNameplateSubtitle_NeverUsesLastThought()
        {
            // Caller must not pass LastThought; activity fallback is truncated short label only.
            string line = AgentDisplayLabels.FormatNameplateSubtitle(
                "菜贩",
                includeMood: true,
                mood: -0.2,
                activityFallback: "王婶想着脏水泼摊位的事");
            Assert.AreEqual("菜贩 · 低落", line);
            Assert.IsFalse(line.Contains("脏水"));
        }
    }
}
