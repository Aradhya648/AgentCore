using System.Collections.Generic;
using AgentTown.Town;

namespace AgentTown.Simulation
{
    /// <summary>
    /// One row for the Decisions inspect tab (header / decision / collapsed moves).
    /// Pure data — HUD maps these to VisualElements.
    /// </summary>
    public sealed class DecisionTabRow
    {
        public bool IsGroupHeader;
        public bool IsCollapsedMoves;
        public int Tick;
        public string Text = "";
        public SimDecision Decision;
    }

    /// <summary>
    /// Client-only readable one-liner for the Decisions inspect tab.
    /// Uses existing <see cref="SimDecision"/> fields + persona/agent name lookup — never invents data.
    /// Also owns story/noise scoring shared by HUD grouping.
    /// </summary>
    public static class DecisionSummary
    {
        private const int DefaultMaxRows = 40;
        private const int MaxIdleMovesPerTick = 3;

        /// <summary>
        /// Preferred primary line: 「姓名 · 行动/区域 · 短理由」.
        /// Falls back to whatever non-empty fields exist (never fabricates).
        /// </summary>
        public static string FormatPrimaryLine(SimDecision decision, SimulationSession session)
        {
            if (decision == null)
            {
                return "";
            }

            string who = ResolveDisplayName(decision.AgentId, session);
            string action = FormatActionClause(decision);
            string reason = FormatReasonClause(decision, action);

            if (!string.IsNullOrEmpty(who) && !string.IsNullOrEmpty(action) && !string.IsNullOrEmpty(reason))
            {
                return $"{who} · {action} · {reason}";
            }

            if (!string.IsNullOrEmpty(who) && !string.IsNullOrEmpty(action))
            {
                return $"{who} · {action}";
            }

            if (!string.IsNullOrEmpty(who) && !string.IsNullOrEmpty(reason))
            {
                return $"{who} · {reason}";
            }

            if (!string.IsNullOrEmpty(action) && !string.IsNullOrEmpty(reason))
            {
                return $"{action} · {reason}";
            }

            if (!string.IsNullOrEmpty(who))
            {
                return who;
            }

            if (!string.IsNullOrEmpty(action))
            {
                return action;
            }

            if (!string.IsNullOrEmpty(reason))
            {
                return reason;
            }

            // Last resort: raw action type or agent id (existing fields only).
            if (!string.IsNullOrEmpty(decision.ActionType))
            {
                return decision.ActionType;
            }

            return string.IsNullOrEmpty(decision.AgentId) ? "—" : decision.AgentId;
        }

        /// <summary>Secondary meta line: tick (+ raw action type when not already used as the action clause).</summary>
        public static string FormatMetaLine(SimDecision decision)
        {
            if (decision == null)
            {
                return "";
            }

            string tick = $"T{decision.Tick}";
            string actionType = decision.ActionType ?? "";
            if (string.IsNullOrEmpty(actionType))
            {
                return tick;
            }

            // If action clause already shows a human label, keep type as quiet meta.
            return $"{tick} · {actionType}";
        }

        /// <summary>
        /// Higher = more story-like. conversation/trade/vote beat idle move_to noise.
        /// </summary>
        public static int StoryDecisionScore(SimDecision decision)
        {
            if (decision == null)
            {
                return 0;
            }

            string action = (decision.ActionType ?? "").ToLowerInvariant();
            if (action == "conversation" || action == "trade" || action == "vote")
            {
                return 3;
            }

            if (LooksLikeStorySummary(decision.Summary))
            {
                return 2;
            }

            return 0;
        }

        /// <summary>move_to / travel-like actions, or idle 「闲逛」 summaries.</summary>
        public static bool IsMoveNoise(SimDecision decision)
        {
            if (decision == null)
            {
                return false;
            }

            if (IsMoveLike(decision.ActionType))
            {
                return true;
            }

            string summary = decision.Summary ?? "";
            return summary.Contains("闲逛");
        }

        /// <summary>Story keywords in a decision summary (涨价风波 / vote / …).</summary>
        public static bool LooksLikeStorySummary(string summary)
        {
            if (string.IsNullOrEmpty(summary))
            {
                return false;
            }

            return summary.Contains("涨价风波")
                || summary.Contains("投票")
                || summary.Contains("表决")
                || summary.Contains("刘警官")
                || summary.Contains("夜市")
                || summary.Contains("限价")
                || summary.Contains("避险")
                || summary.Contains("节日");
        }

        /// <summary>
        /// Group by tick (story ticks first), rank story rows above move noise,
        /// and collapse move_to/闲逛 when the tick already has story content.
        /// </summary>
        public static List<DecisionTabRow> BuildTabRows(
            IReadOnlyList<SimDecision> decisions,
            int maxRows = DefaultMaxRows)
        {
            var result = new List<DecisionTabRow>();
            if (decisions == null || decisions.Count == 0 || maxRows <= 0)
            {
                return result;
            }

            var byTick = new Dictionary<int, List<SimDecision>>();
            var tickOrder = new List<int>();
            foreach (SimDecision d in decisions)
            {
                if (d == null)
                {
                    continue;
                }

                if (!byTick.TryGetValue(d.Tick, out List<SimDecision> list))
                {
                    list = new List<SimDecision>();
                    byTick[d.Tick] = list;
                    tickOrder.Add(d.Tick);
                }

                list.Add(d);
            }

            tickOrder.Sort((a, b) =>
            {
                int storyA = TickHasStory(byTick[a]) ? 1 : 0;
                int storyB = TickHasStory(byTick[b]) ? 1 : 0;
                int storyCmp = storyB.CompareTo(storyA);
                if (storyCmp != 0)
                {
                    return storyCmp;
                }

                return b.CompareTo(a);
            });

            foreach (int tick in tickOrder)
            {
                if (result.Count >= maxRows)
                {
                    break;
                }

                List<SimDecision> group = byTick[tick];
                group.Sort((a, b) =>
                {
                    int score = StoryDecisionScore(b).CompareTo(StoryDecisionScore(a));
                    if (score != 0)
                    {
                        return score;
                    }

                    // Stable-ish: non-noise before noise when scores tie.
                    int noise = (IsMoveNoise(a) ? 1 : 0).CompareTo(IsMoveNoise(b) ? 1 : 0);
                    if (noise != 0)
                    {
                        return noise;
                    }

                    return string.CompareOrdinal(a.AgentId, b.AgentId);
                });

                bool hasStory = TickHasStory(group);
                string headerTag = ShortStoryTag(group);
                string headerText = string.IsNullOrEmpty(headerTag)
                    ? $"T{tick}"
                    : $"T{tick} · {headerTag}";

                result.Add(new DecisionTabRow
                {
                    IsGroupHeader = true,
                    Tick = tick,
                    Text = headerText,
                });

                int moveNoiseCount = 0;
                int idleMovesShown = 0;

                foreach (SimDecision decision in group)
                {
                    if (result.Count >= maxRows)
                    {
                        break;
                    }

                    if (IsMoveNoise(decision))
                    {
                        if (hasStory)
                        {
                            moveNoiseCount++;
                            continue;
                        }

                        if (idleMovesShown >= MaxIdleMovesPerTick)
                        {
                            moveNoiseCount++;
                            continue;
                        }

                        idleMovesShown++;
                        result.Add(new DecisionTabRow
                        {
                            Tick = tick,
                            Decision = decision,
                        });
                        continue;
                    }

                    result.Add(new DecisionTabRow
                    {
                        Tick = tick,
                        Decision = decision,
                    });
                }

                // Story ticks: fold all move noise. Idle ticks: fold overflow past the small sample.
                if (moveNoiseCount > 0 && result.Count < maxRows)
                {
                    result.Add(new DecisionTabRow
                    {
                        IsCollapsedMoves = true,
                        Tick = tick,
                        Text = $"{moveNoiseCount} 次移动",
                    });
                }
            }

            return result;
        }

        internal static string ResolveDisplayName(string agentId, SimulationSession session)
        {
            if (string.IsNullOrEmpty(agentId))
            {
                return "";
            }

            if (session?.Agents != null
                && session.Agents.TryGetValue(agentId, out SimAgentState state)
                && state != null
                && !string.IsNullOrEmpty(state.Name))
            {
                return state.Name;
            }

            LocalPersona persona = TownPersonas.Get(agentId);
            if (persona != null && !string.IsNullOrEmpty(persona.Name))
            {
                return persona.Name;
            }

            return agentId;
        }

        private static bool TickHasStory(List<SimDecision> group)
        {
            foreach (SimDecision d in group)
            {
                if (StoryDecisionScore(d) > 0)
                {
                    return true;
                }
            }

            return false;
        }

        private static string ShortStoryTag(List<SimDecision> group)
        {
            int best = 0;
            string tag = "";
            foreach (SimDecision d in group)
            {
                int score = StoryDecisionScore(d);
                if (score <= best)
                {
                    continue;
                }

                best = score;
                string action = (d.ActionType ?? "").ToLowerInvariant();
                string summary = d.Summary ?? "";
                if (action == "vote" || summary.Contains("投票") || summary.Contains("表决"))
                {
                    tag = "投票";
                }
                else if (action == "trade")
                {
                    tag = "交易";
                }
                else if (action == "conversation")
                {
                    tag = summary.Contains("涨价风波") ? "涨价风波" : "对话";
                }
                else if (LooksLikeStorySummary(summary))
                {
                    if (summary.Contains("涨价风波"))
                    {
                        tag = "涨价风波";
                    }
                    else if (summary.Contains("投票") || summary.Contains("表决"))
                    {
                        tag = "投票";
                    }
                    else
                    {
                        tag = "故事";
                    }
                }
            }

            return tag;
        }

        private static string FormatActionClause(SimDecision decision)
        {
            string location = decision.Location ?? "";
            string actionType = decision.ActionType ?? "";

            if (!string.IsNullOrEmpty(location))
            {
                if (IsMoveLike(actionType) || string.IsNullOrEmpty(actionType))
                {
                    return $"前往{location}";
                }

                return $"{HumanizeActionType(actionType)} · {location}";
            }

            if (!string.IsNullOrEmpty(actionType))
            {
                return HumanizeActionType(actionType);
            }

            // No typed action — if Summary looks like a destination phrase, use it as action.
            string summary = decision.Summary ?? "";
            if (summary.StartsWith("前往") && summary.Length <= 24)
            {
                return summary;
            }

            return "";
        }

        private static string FormatReasonClause(SimDecision decision, string actionClause)
        {
            string summary = (decision.Summary ?? "").Trim();
            if (string.IsNullOrEmpty(summary))
            {
                return "";
            }

            // Avoid duplicating the action clause ("前往市场 · 前往市场").
            if (!string.IsNullOrEmpty(actionClause) && summary == actionClause)
            {
                return "";
            }

            if (!string.IsNullOrEmpty(actionClause)
                && summary.StartsWith("前往")
                && actionClause.StartsWith("前往")
                && summary.Length <= 24)
            {
                return "";
            }

            // Story beats (涨价风波 / vote) need a longer window than idle "闲逛".
            int maxChars = LooksLikeStorySummary(summary) ? 72 : 48;
            return Truncate(summary, maxChars);
        }

        private static bool IsMoveLike(string actionType)
        {
            if (string.IsNullOrEmpty(actionType))
            {
                return false;
            }

            string t = actionType.ToLowerInvariant();
            return t == "move_to" || t == "move" || t == "goto" || t == "go_to" || t == "travel";
        }

        private static string HumanizeActionType(string actionType)
        {
            switch (actionType.ToLowerInvariant())
            {
                case "move_to":
                case "move":
                case "goto":
                case "go_to":
                case "travel":
                    return "移动";
                case "conversation":
                case "talk":
                case "chat":
                    return "对话";
                case "trade":
                    return "交易";
                case "vote":
                    return "投票";
                case "work":
                    return "工作";
                case "rest":
                    return "休息";
                default:
                    return actionType;
            }
        }

        private static string Truncate(string value, int maxChars)
        {
            if (string.IsNullOrEmpty(value) || value.Length <= maxChars)
            {
                return value;
            }

            return value.Substring(0, maxChars - 1) + "…";
        }
    }
}
