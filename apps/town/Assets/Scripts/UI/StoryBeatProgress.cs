using System;
using System.Collections.Generic;

namespace AgentTown.UI
{
    /// <summary>
    /// Pure helpers for Offline / Replay story-beat chrome (HUD bar + timeline labels).
    /// EditMode-friendly: no UnityEngine dependency beyond what callers pass in.
    /// </summary>
    public static class StoryBeatProgress
    {
        public readonly struct PulseMark
        {
            public readonly int Tick;
            public readonly string ArcLabel;

            public PulseMark(int tick, string arcLabel)
            {
                Tick = tick;
                ArcLabel = arcLabel ?? "";
            }
        }

        public readonly struct BarState
        {
            public readonly string Text;
            public readonly int CurrentIndex; // 1-based when on a pulse; 0 when idle / daily
            public readonly int TotalBeats;
            public readonly string ArcLabel;
            public readonly bool OnPulse;

            public BarState(string text, int currentIndex, int totalBeats, string arcLabel, bool onPulse)
            {
                Text = text ?? "";
                CurrentIndex = currentIndex;
                TotalBeats = totalBeats;
                ArcLabel = arcLabel ?? "";
                OnPulse = onPulse;
            }
        }

        public readonly struct TimelineHint
        {
            public readonly string CurrentLabel;
            public readonly string NextLabel;
            public readonly string Combined;

            public TimelineHint(string currentLabel, string nextLabel, string combined)
            {
                CurrentLabel = currentLabel ?? "";
                NextLabel = nextLabel ?? "";
                Combined = combined ?? "";
            }
        }

        /// <summary>
        /// Format top/bottom beat bar: <c>{pack} · {i}/{n} · {arc}</c>, or pack / 「日常」 when idle.
        /// </summary>
        public static BarState Resolve(
            string packDisplayName,
            int displayTick,
            IReadOnlyList<PulseMark> pulses)
        {
            string pack = string.IsNullOrWhiteSpace(packDisplayName) ? "演示" : packDisplayName.Trim();
            if (pulses == null || pulses.Count == 0)
            {
                return new BarState($"{pack} · 日常", 0, 0, "日常", false);
            }

            int total = pulses.Count;
            int currentIdx = -1; // 0-based index of pulse at-or-before displayTick
            for (int i = 0; i < pulses.Count; i++)
            {
                if (pulses[i].Tick <= displayTick)
                {
                    currentIdx = i;
                }
                else
                {
                    break;
                }
            }

            if (currentIdx < 0)
            {
                // Before first pulse — still show pack + upcoming first beat hint as 日常.
                string first = ShortArc(pulses[0].ArcLabel);
                string idle = string.IsNullOrEmpty(first)
                    ? $"{pack} · 日常"
                    : $"{pack} · 日常 · 即将「{first}」";
                return new BarState(idle, 0, total, "日常", false);
            }

            PulseMark mark = pulses[currentIdx];
            bool onPulse = mark.Tick == displayTick;
            string arc = string.IsNullOrEmpty(mark.ArcLabel) ? (onPulse ? "故事" : "日常") : mark.ArcLabel;
            // Between pulses: keep last beat index so viewers still know "which act", label stays arc.
            string text = $"{pack} · {currentIdx + 1}/{total} · {arc}";
            return new BarState(text, currentIdx + 1, total, arc, onPulse);
        }

        /// <summary>Seek-adjacent labels: current pulse + next pulse names.</summary>
        public static TimelineHint ResolveTimeline(
            int displayTick,
            IReadOnlyList<PulseMark> pulses)
        {
            if (pulses == null || pulses.Count == 0)
            {
                return new TimelineHint("日常", "", "日常");
            }

            int currentIdx = -1;
            int nextIdx = -1;
            for (int i = 0; i < pulses.Count; i++)
            {
                if (pulses[i].Tick <= displayTick)
                {
                    currentIdx = i;
                }
                else if (nextIdx < 0)
                {
                    nextIdx = i;
                }
            }

            string current = currentIdx >= 0
                ? ShortArc(pulses[currentIdx].ArcLabel)
                : "日常";
            if (string.IsNullOrEmpty(current))
            {
                current = currentIdx >= 0 ? $"第{currentIdx + 1}拍" : "日常";
            }

            string next = "";
            if (nextIdx >= 0)
            {
                next = ShortArc(pulses[nextIdx].ArcLabel);
                if (string.IsNullOrEmpty(next))
                {
                    next = $"第{nextIdx + 1}拍";
                }
            }

            string combined = string.IsNullOrEmpty(next)
                ? $"当前 {current}"
                : $"当前 {current} · 下一 {next}";
            return new TimelineHint(current, next, combined);
        }

        /// <summary>Tooltip while dragging the seek slider to a candidate tick.</summary>
        public static string TooltipForTick(int tick, IReadOnlyList<PulseMark> pulses)
        {
            if (pulses == null || pulses.Count == 0)
            {
                return $"Tick {tick}";
            }

            for (int i = 0; i < pulses.Count; i++)
            {
                if (pulses[i].Tick == tick)
                {
                    string arc = ShortArc(pulses[i].ArcLabel);
                    return string.IsNullOrEmpty(arc)
                        ? $"Tick {tick} · 第{i + 1}拍"
                        : $"Tick {tick} · {arc}";
                }
            }

            TimelineHint hint = ResolveTimeline(tick, pulses);
            return $"Tick {tick} · {hint.CurrentLabel}";
        }

        /// <summary>Build pulse marks from Offline interaction list (tick ascending).</summary>
        public static List<PulseMark> FromInteractions(
            IEnumerable<AgentTown.Simulation.ActiveInteraction> interactions)
        {
            var list = new List<PulseMark>();
            if (interactions == null)
            {
                return list;
            }

            foreach (AgentTown.Simulation.ActiveInteraction ix in interactions)
            {
                if (ix == null || ix.Tick <= 0)
                {
                    continue;
                }

                string arc = ExtractArcLabel(ix.Summary);
                list.Add(new PulseMark(ix.Tick, arc));
            }

            list.Sort((a, b) => a.Tick.CompareTo(b.Tick));
            return list;
        }

        /// <summary>Pull「包名·弧」from interaction summary like <c>tick3 赵…（涨价风波·试探）</c>.</summary>
        public static string ExtractArcLabel(string summary)
        {
            if (string.IsNullOrEmpty(summary))
            {
                return "";
            }

            int open = summary.LastIndexOf('（');
            int close = summary.LastIndexOf('）');
            if (open >= 0 && close > open)
            {
                return summary.Substring(open + 1, close - open - 1).Trim();
            }

            open = summary.LastIndexOf('(');
            close = summary.LastIndexOf(')');
            if (open >= 0 && close > open)
            {
                return summary.Substring(open + 1, close - open - 1).Trim();
            }

            return "";
        }

        /// <summary>Prefer the segment after · so the bar stays short.</summary>
        public static string ShortArc(string arcLabel)
        {
            if (string.IsNullOrEmpty(arcLabel))
            {
                return "";
            }

            int dot = arcLabel.IndexOf('·');
            if (dot >= 0 && dot + 1 < arcLabel.Length)
            {
                return arcLabel.Substring(dot + 1).Trim();
            }

            return arcLabel.Trim();
        }
    }
}
