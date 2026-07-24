using System;
using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AgentTown.Simulation
{
    /// <summary>Wire shape for one interaction result inside <c>sim.interaction</c> payload.</summary>
    public sealed class InteractionResult
    {
        [JsonProperty("request_id")] public string RequestId = "";
        [JsonProperty("kind")] public string Kind = "";
        [JsonProperty("status")] public string Status = "";
        [JsonProperty("initiator_id")] public string InitiatorId = "";
        [JsonProperty("target_id")] public string TargetId;
        [JsonProperty("summary")] public string Summary = "";
        [JsonProperty("transcript")] public List<InteractionTranscriptLine> Transcript = new();
        [JsonProperty("state_changes")] public InteractionStateChanges StateChanges;
        [JsonProperty("detail")] public string Detail = "";
    }

    public sealed class InteractionTranscriptLine
    {
        [JsonProperty("speaker_id")] public string SpeakerId = "";
        [JsonProperty("speaker_name")] public string SpeakerName = "";
        [JsonProperty("text")] public string Text = "";
        [JsonProperty("round")] public int Round;
    }

    public sealed class InteractionStateChanges
    {
        [JsonProperty("mood_deltas")] public Dictionary<string, double> MoodDeltas = new();
        [JsonProperty("money_transfers")] public List<JObject> MoneyTransfers = new();
        [JsonProperty("inventory_transfers")] public List<JObject> InventoryTransfers = new();
        [JsonProperty("governance")] public JObject Governance;
    }

    /// <summary>Client-side active overlay row — semantic port of Desktop <c>ActiveInteraction</c>.</summary>
    public sealed class ActiveInteraction
    {
        public string Id = "";
        public int Tick;
        public string Kind = "";
        public string Status = "";
        public string InitiatorId = "";
        public string TargetId;
        public string Summary = "";
        public List<InteractionTranscriptLine> Transcript = new();
        public InteractionStateChanges StateChanges;
        public string Detail = "";
        /// <summary>Wall-clock expiry for live TTL; offline cues use <see cref="float.PositiveInfinity"/>.</summary>
        public float ExpiresAtRealtime = float.PositiveInfinity;
    }

    public static class InteractionModel
    {
        private static readonly Dictionary<string, float> TtlSeconds = new()
        {
            // Multi-line Live bubbles need longer wall-clock TTL to finish reading.
            ["conversation"] = 10f,
            ["trade"] = 3f,
            ["vote"] = 5f,
        };

        /// <summary>
        /// World-space label height (px) for overlay text — grows with line count so
        /// 2–3 line conversation bubbles are not clipped.
        /// </summary>
        public static float BubbleHeightPx(string text, float minHeight = 64f, float maxHeight = 200f)
        {
            int lines = 1;
            if (!string.IsNullOrEmpty(text))
            {
                lines = 1;
                for (int i = 0; i < text.Length; i++)
                {
                    if (text[i] == '\n')
                    {
                        lines++;
                    }
                }
            }

            float height = 36f + lines * 32f;
            if (height < minHeight)
            {
                return minHeight;
            }

            if (height > maxHeight)
            {
                return maxHeight;
            }

            return height;
        }

        public static float TtlForKind(string kind)
        {
            if (!string.IsNullOrEmpty(kind) && TtlSeconds.TryGetValue(kind, out float ttl))
            {
                return ttl;
            }

            return 4f;
        }

        /// <summary>
        /// Offline playhead dwell window in ticks (full opacity). Higher playback speed
        /// shortens the readable window so cues do not linger forever at 4×.
        /// </summary>
        public static int OfflineHoldTicks(string kind, float playbackSpeed)
        {
            float baseHold = kind switch
            {
                "trade" => 1.5f,
                "vote" => 2.5f,
                // Conversation bubbles may show several lines — hold a beat longer.
                "conversation" => 3.5f,
                _ => 2f,
            };
            float speed = playbackSpeed < 0.1f ? 0.1f : playbackSpeed;
            return System.Math.Max(1, (int)System.Math.Ceiling(baseHold / speed));
        }

        /// <summary>Offline fade length in ticks after the hold window (also speed-scaled).</summary>
        public static int OfflineFadeTicks(float playbackSpeed)
        {
            float speed = playbackSpeed < 0.1f ? 0.1f : playbackSpeed;
            return System.Math.Max(1, (int)System.Math.Ceiling(1.5f / speed));
        }

        /// <summary>
        /// Overlay opacity for Offline scrubbing / autoplay. Live uses wall-clock TTL
        /// (caller prunes); Offline stays readable near the playhead then fades out.
        /// </summary>
        public static float OverlayAlpha(
            ActiveInteraction interaction,
            int displayTick,
            bool offline,
            float playbackSpeed)
        {
            if (interaction == null)
            {
                return 0f;
            }

            if (!offline)
            {
                return 1f;
            }

            int age = displayTick - interaction.Tick;
            if (age < 0)
            {
                return 0f;
            }

            int hold = OfflineHoldTicks(interaction.Kind, playbackSpeed);
            if (age <= hold)
            {
                return 1f;
            }

            int fade = OfflineFadeTicks(playbackSpeed);
            int intoFade = age - hold;
            if (intoFade >= fade)
            {
                return 0f;
            }

            return 1f - (intoFade / (float)fade);
        }

        public static ActiveInteraction FromResult(InteractionResult result, int tick, float nowRealtime, bool persistent)
        {
            if (result == null)
            {
                return null;
            }

            string kind = result.Kind ?? "";
            return new ActiveInteraction
            {
                Id = string.IsNullOrEmpty(result.RequestId) ? $"ix-{tick}-{kind}" : result.RequestId,
                Tick = tick,
                Kind = kind,
                Status = result.Status ?? "",
                InitiatorId = result.InitiatorId ?? "",
                TargetId = result.TargetId,
                Summary = result.Summary ?? "",
                Transcript = result.Transcript ?? new List<InteractionTranscriptLine>(),
                StateChanges = result.StateChanges,
                Detail = result.Detail ?? "",
                ExpiresAtRealtime = persistent
                    ? float.PositiveInfinity
                    : nowRealtime + TtlForKind(kind),
            };
        }

        public static bool TryParseFromPayload(JObject payload, float nowRealtime, bool persistent, out ActiveInteraction interaction)
        {
            interaction = null;
            if (payload == null)
            {
                return false;
            }

            int tick = payload["tick"]?.Value<int>() ?? 0;
            if (payload["interaction"] is not JObject ixObj)
            {
                return false;
            }

            InteractionResult result;
            try
            {
                result = ixObj.ToObject<InteractionResult>(SimJson.Serializer);
            }
            catch (JsonException)
            {
                return false;
            }

            interaction = FromResult(result, tick, nowRealtime, persistent);
            return interaction != null;
        }

        public static string Truncate(string text, int maxLen = 48)
        {
            if (string.IsNullOrEmpty(text))
            {
                return "";
            }

            string trimmed = text.Trim();
            if (trimmed.Length <= maxLen)
            {
                return trimmed;
            }

            return trimmed.Substring(0, Math.Max(1, maxLen - 1)) + "…";
        }

        public static string LastLineForAgent(IReadOnlyList<InteractionTranscriptLine> transcript, string agentId)
        {
            if (transcript == null || string.IsNullOrEmpty(agentId))
            {
                return null;
            }

            for (int i = transcript.Count - 1; i >= 0; i--)
            {
                InteractionTranscriptLine line = transcript[i];
                if (line != null && line.SpeakerId == agentId)
                {
                    return line.Text;
                }
            }

            return null;
        }

        /// <summary>
        /// Format transcript as readable multi-line text (<c>名：台词</c> per line).
        /// Empty / null transcript → empty string.
        /// </summary>
        public static string FormatTranscript(IReadOnlyList<InteractionTranscriptLine> transcript)
        {
            if (transcript == null || transcript.Count == 0)
            {
                return "";
            }

            var parts = new List<string>(transcript.Count);
            foreach (InteractionTranscriptLine line in transcript)
            {
                if (line == null || string.IsNullOrWhiteSpace(line.Text))
                {
                    continue;
                }

                string name = string.IsNullOrWhiteSpace(line.SpeakerName)
                    ? (string.IsNullOrWhiteSpace(line.SpeakerId) ? "?" : line.SpeakerId)
                    : line.SpeakerName.Trim();
                parts.Add($"{name}：{line.Text.Trim()}");
            }

            return parts.Count == 0 ? "" : string.Join("\n", parts);
        }

        /// <summary>
        /// All lines spoken by <paramref name="agentId"/>, joined with newlines.
        /// Each line is truncated; total capped at <paramref name="maxLines"/> rows.
        /// </summary>
        public static string LinesForAgent(
            IReadOnlyList<InteractionTranscriptLine> transcript,
            string agentId,
            int maxLines = 3,
            int maxLineLen = 40)
        {
            if (transcript == null || string.IsNullOrEmpty(agentId) || maxLines <= 0)
            {
                return null;
            }

            var parts = new List<string>(maxLines);
            foreach (InteractionTranscriptLine line in transcript)
            {
                if (line == null || line.SpeakerId != agentId || string.IsNullOrWhiteSpace(line.Text))
                {
                    continue;
                }

                parts.Add(Truncate(line.Text, maxLineLen));
                if (parts.Count >= maxLines)
                {
                    break;
                }
            }

            return parts.Count == 0 ? null : string.Join("\n", parts);
        }

        public static bool Succeeded(string status) =>
            string.Equals(status, "completed", StringComparison.OrdinalIgnoreCase);

        public static string TradeBriefLabel(ActiveInteraction interaction)
        {
            if (interaction?.StateChanges?.InventoryTransfers != null
                && interaction.StateChanges.InventoryTransfers.Count > 0)
            {
                JObject transfer = interaction.StateChanges.InventoryTransfers[0];
                string item = transfer?["item"]?.Value<string>() ?? "物品";
                int qty = transfer?["quantity"]?.Value<int>() ?? 1;
                if (interaction.StateChanges.MoneyTransfers != null
                    && interaction.StateChanges.MoneyTransfers.Count > 0)
                {
                    double amount = interaction.StateChanges.MoneyTransfers[0]?["amount"]?.Value<double>() ?? 0;
                    return $"{item}×{qty} · {amount:0} 币";
                }

                return $"{item}×{qty}";
            }

            return Truncate(interaction?.Summary ?? "", 40);
        }

        public static void VoteGovernanceDetails(
            InteractionStateChanges stateChanges,
            out string motion,
            out string outcome,
            out int yes,
            out int no,
            out int abstain)
        {
            motion = "";
            outcome = "";
            yes = 0;
            no = 0;
            abstain = 0;
            JObject gov = stateChanges?.Governance;
            if (gov == null)
            {
                return;
            }

            motion = gov["motion"]?.Value<string>() ?? "";
            outcome = gov["outcome"]?.Value<string>() ?? "";
            yes = gov["yes"]?.Value<int>() ?? 0;
            no = gov["no"]?.Value<int>() ?? 0;
            abstain = gov["abstain"]?.Value<int>() ?? 0;
        }
    }
}
