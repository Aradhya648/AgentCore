using System.Collections.Generic;
using AgentTown.Simulation;
using AgentTown.UI;
using NUnit.Framework;

namespace AgentTown.Tests
{
    public sealed class StoryBeatProgressTests
    {
        [Test]
        public void Resolve_OnPulse_ShowsIndexAndArc()
        {
            var pulses = new List<StoryBeatProgress.PulseMark>
            {
                new StoryBeatProgress.PulseMark(3, "涨价风波·试探"),
                new StoryBeatProgress.PulseMark(6, "涨价风波·趁乱"),
                new StoryBeatProgress.PulseMark(9, "涨价风波·爆发"),
            };

            StoryBeatProgress.BarState at3 = StoryBeatProgress.Resolve("涨价风波", 3, pulses);
            Assert.IsTrue(at3.OnPulse);
            Assert.AreEqual(1, at3.CurrentIndex);
            Assert.AreEqual(3, at3.TotalBeats);
            Assert.IsTrue(at3.Text.Contains("1/3"));
            Assert.IsTrue(at3.Text.Contains("试探") || at3.Text.Contains("涨价风波·试探"));

            StoryBeatProgress.BarState between = StoryBeatProgress.Resolve("涨价风波", 4, pulses);
            Assert.IsFalse(between.OnPulse);
            Assert.AreEqual(1, between.CurrentIndex);
            Assert.IsTrue(between.Text.Contains("1/3"));

            StoryBeatProgress.BarState before = StoryBeatProgress.Resolve("涨价风波", 1, pulses);
            Assert.IsFalse(before.OnPulse);
            Assert.IsTrue(before.Text.Contains("日常"));
        }

        [Test]
        public void Resolve_EmptyPulses_ShowsDaily()
        {
            StoryBeatProgress.BarState bar = StoryBeatProgress.Resolve("节日庆典", 5, null);
            Assert.IsTrue(bar.Text.Contains("日常"));
            Assert.AreEqual(0, bar.TotalBeats);
        }

        [Test]
        public void Timeline_AndTooltip_MatchNextStoryCadence()
        {
            var pulses = new List<StoryBeatProgress.PulseMark>
            {
                new StoryBeatProgress.PulseMark(3, "涨价风波·试探"),
                new StoryBeatProgress.PulseMark(6, "涨价风波·趁乱"),
            };

            StoryBeatProgress.TimelineHint at3 = StoryBeatProgress.ResolveTimeline(3, pulses);
            Assert.IsTrue(at3.CurrentLabel.Contains("试探"));
            Assert.IsTrue(at3.NextLabel.Contains("趁乱"));
            Assert.IsTrue(at3.Combined.Contains("下一"));

            string tip = StoryBeatProgress.TooltipForTick(6, pulses);
            Assert.IsTrue(tip.Contains("6"));
            Assert.IsTrue(tip.Contains("趁乱"));
        }

        [Test]
        public void FromInteractions_ExtractsArcLabels()
        {
            var interactions = new List<ActiveInteraction>
            {
                new ActiveInteraction
                {
                    Tick = 3,
                    Kind = "conversation",
                    Summary = "tick3 赵老板与王婶（涨价风波·试探）",
                },
                new ActiveInteraction
                {
                    Tick = 6,
                    Kind = "trade",
                    Summary = "tick6 成交：…（涨价风波·趁乱）",
                },
            };

            List<StoryBeatProgress.PulseMark> marks = StoryBeatProgress.FromInteractions(interactions);
            Assert.AreEqual(2, marks.Count);
            Assert.AreEqual(3, marks[0].Tick);
            Assert.AreEqual("涨价风波·试探", marks[0].ArcLabel);
            Assert.AreEqual("涨价风波·趁乱", marks[1].ArcLabel);
            Assert.AreEqual("试探", StoryBeatProgress.ShortArc(marks[0].ArcLabel));
        }
    }
}
