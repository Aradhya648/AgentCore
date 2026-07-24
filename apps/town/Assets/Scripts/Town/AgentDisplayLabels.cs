namespace AgentTown.Town
{
    /// <summary>
    /// Shared short labels for HUD resident detail and world-space nameplates.
    /// One mood threshold table — never fork copy in callers.
    /// </summary>
    public static class AgentDisplayLabels
    {
        /// <summary>Short mood word for HUD + nameplate (thresholds shared).</summary>
        public static string MoodLabel(double mood)
        {
            if (mood >= 0.5) return "愉快";
            if (mood >= 0.15) return "平静";
            if (mood >= -0.15) return "一般";
            if (mood >= -0.5) return "低落";
            return "沮丧";
        }

        /// <summary>
        /// Nameplate subtitle: <c>Role · Mood</c> when both exist; degrade to whichever is present.
        /// Never uses LastThought. Long activity only as last-resort fallback (truncated).
        /// </summary>
        public static string FormatNameplateSubtitle(
            string role,
            bool includeMood,
            double mood,
            string activityFallback = "",
            int maxActivityChars = 16)
        {
            string rolePart = string.IsNullOrEmpty(role) ? "" : role.Trim();
            string moodPart = includeMood ? MoodLabel(mood) : "";

            if (!string.IsNullOrEmpty(rolePart) && !string.IsNullOrEmpty(moodPart))
            {
                return $"{rolePart} · {moodPart}";
            }

            if (!string.IsNullOrEmpty(rolePart))
            {
                return rolePart;
            }

            if (!string.IsNullOrEmpty(moodPart))
            {
                return moodPart;
            }

            return Truncate(activityFallback ?? "", maxActivityChars);
        }

        private static string Truncate(string value, int maxChars)
        {
            if (string.IsNullOrEmpty(value) || maxChars <= 0 || value.Length <= maxChars)
            {
                return value ?? "";
            }

            if (maxChars == 1)
            {
                return "…";
            }

            return value.Substring(0, maxChars - 1) + "…";
        }
    }
}
