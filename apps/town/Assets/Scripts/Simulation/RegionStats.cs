using System.Collections.Generic;
using UnityEngine;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Pure region aggregation for mood/density heatmaps — semantic port of Desktop
    /// <c>regionStats.ts</c> (not a React copy).
    /// </summary>
    public enum MoodBand
    {
        Good,
        Medium,
        Bad,
    }

    public readonly struct RegionStat
    {
        public readonly string Id;
        public readonly string Label;
        public readonly int Population;
        public readonly double AvgMood;
        public readonly float PopulationRatio;

        public RegionStat(string id, string label, int population, double avgMood, float populationRatio)
        {
            Id = id;
            Label = label;
            Population = population;
            AvgMood = avgMood;
            PopulationRatio = populationRatio;
        }
    }

    public static class RegionStats
    {
        /// <summary>Mood is on [-1, 1] in the simulation model.</summary>
        public static MoodBand MoodBandOf(double mood)
        {
            if (mood > 0.3) return MoodBand.Good;
            if (mood < -0.3) return MoodBand.Bad;
            return MoodBand.Medium;
        }

        /// <summary>Heatmap tint — mood drives hue, population drives alpha.</summary>
        public static Color MoodHeatmapColor(double mood, float populationRatio)
        {
            MoodBand band = MoodBandOf(mood);
            float opacity = 0.12f + populationRatio * 0.28f;
            Color rgb = band switch
            {
                MoodBand.Good => new Color(0.133f, 0.773f, 0.369f),
                MoodBand.Bad => new Color(0.937f, 0.267f, 0.267f),
                _ => new Color(0.918f, 0.702f, 0.031f),
            };
            rgb.a = opacity;
            return rgb;
        }

        /// <summary>
        /// Aggregate agents by <see cref="SimAgentState.Location"/> over the given region ids.
        /// Regions with no agents still appear (population 0, avg mood 0).
        /// </summary>
        public static List<RegionStat> Compute(
            IReadOnlyDictionary<string, SimAgentState> agents,
            IReadOnlyList<string> regionIds)
        {
            var result = new List<RegionStat>();
            if (regionIds == null || regionIds.Count == 0)
            {
                return result;
            }

            var byRegion = new Dictionary<string, List<SimAgentState>>();
            for (int i = 0; i < regionIds.Count; i++)
            {
                string id = regionIds[i];
                if (!string.IsNullOrEmpty(id) && !byRegion.ContainsKey(id))
                {
                    byRegion[id] = new List<SimAgentState>();
                }
            }

            int totalAgents = 0;
            if (agents != null)
            {
                foreach (KeyValuePair<string, SimAgentState> pair in agents)
                {
                    SimAgentState agent = pair.Value;
                    if (agent == null)
                    {
                        continue;
                    }

                    totalAgents++;
                    string loc = agent.Location ?? "";
                    if (byRegion.TryGetValue(loc, out List<SimAgentState> bucket))
                    {
                        bucket.Add(agent);
                    }
                }
            }

            float denom = totalAgents > 0 ? totalAgents : 1f;

            for (int i = 0; i < regionIds.Count; i++)
            {
                string id = regionIds[i];
                if (string.IsNullOrEmpty(id) || !byRegion.TryGetValue(id, out List<SimAgentState> residents))
                {
                    continue;
                }

                int population = residents.Count;
                double avgMood = 0.0;
                if (population > 0)
                {
                    double sum = 0.0;
                    for (int r = 0; r < residents.Count; r++)
                    {
                        sum += residents[r].Mood;
                    }

                    avgMood = sum / population;
                }

                result.Add(new RegionStat(
                    id,
                    id,
                    population,
                    avgMood,
                    population / denom));
            }

            return result;
        }
    }
}
