using System;
using System.Collections.Generic;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Server-Sent-Events frame decoding, matching the desktop R3F reference
    /// (<c>services/simulation/stream.ts</c>) and the retired UE client: split the byte
    /// stream on blank lines (<c>\n\n</c>), then concatenate the <c>data:</c> lines of
    /// each frame into a single JSON payload string.
    /// </summary>
    internal static class SseFrame
    {
        /// <summary>
        /// Extract the JSON payload from one SSE frame. Returns <c>null</c> if the frame
        /// carries no <c>data:</c> lines (e.g. comment / heartbeat frames).
        /// </summary>
        public static string ExtractData(string frame)
        {
            if (string.IsNullOrEmpty(frame))
            {
                return null;
            }

            List<string> dataLines = null;
            foreach (var rawLine in frame.Split('\n'))
            {
                string line = rawLine.EndsWith("\r", StringComparison.Ordinal)
                    ? rawLine.Substring(0, rawLine.Length - 1)
                    : rawLine;

                if (!line.StartsWith("data:", StringComparison.Ordinal))
                {
                    continue;
                }

                string data = line.Substring(5);
                if (data.StartsWith(" ", StringComparison.Ordinal))
                {
                    data = data.Substring(1);
                }

                (dataLines ??= new List<string>()).Add(data);
            }

            if (dataLines == null || dataLines.Count == 0)
            {
                return null;
            }

            return string.Join("\n", dataLines);
        }
    }
}
