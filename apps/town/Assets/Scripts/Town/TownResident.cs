using System.Collections.Generic;
using AgentTown.Simulation;

namespace AgentTown.Town
{
    /// <summary>
    /// A resident as shown in the UI — the merge of the three §6.4 sources: authoritative manifest
    /// persona (name / role / big_five), local card (bio / relationships fallback), and the live
    /// tick snapshot (mood / activity / location …). This is where §4.3 step 2 (persona merge) is
    /// realised on the presentation side, keeping the batch-1 <see cref="SimulationSession"/> state
    /// machine free of view concerns.
    /// </summary>
    public sealed class ResidentView
    {
        public string AgentId = "";
        public string Name = "";
        public string Role = "";
        public string Bio = "";
        public string Goal = "";
        public string Location = "";
        public string Activity = "";
        public string LastThought = "";
        public double Mood;
        public double Money = 100.0;
        public bool HasLiveState;
        public BigFive BigFive = new();
        public Dictionary<string, double> Relationships = new();
    }

    /// <summary>
    /// Builds the ordered resident roster for the UI by merging the manifest, local personas, and
    /// live agent snapshots. Roster order is manifest-first (authoritative), falling back to the
    /// local persona list so the panel is populated offline before a manifest is fetched.
    /// </summary>
    public static class TownResidents
    {
        public static List<ResidentView> Build(SimulationSession session)
        {
            var views = new List<ResidentView>();
            if (session == null)
            {
                return views;
            }

            foreach (string agentId in RosterOrder(session))
            {
                views.Add(Merge(agentId, session));
            }

            return views;
        }

        public static ResidentView Merge(string agentId, SimulationSession session)
        {
            SimPersona manifestPersona = FindManifestPersona(session, agentId);
            LocalPersona local = TownPersonas.Get(agentId);
            session.Agents.TryGetValue(agentId, out SimAgentState live);

            var view = new ResidentView
            {
                AgentId = agentId,
                Name = FirstNonEmpty(manifestPersona?.Name, local?.Name, live?.Name, agentId),
                Role = FirstNonEmpty(manifestPersona?.Role, local?.Role, live?.Role),
                Bio = local?.Bio ?? "",
                // Live goal wins (it reflects the current tick); otherwise fall back to persona goal.
                Goal = FirstNonEmpty(live?.Goal, manifestPersona?.Goal, local?.Goal),
                // §4.3 step 2: big_five is authoritative from the manifest, local card as fallback.
                BigFive = manifestPersona?.BigFive ?? local?.BigFive ?? new BigFive(),
            };

            if (live != null)
            {
                view.HasLiveState = true;
                view.Location = live.Location ?? "";
                view.Activity = live.Activity ?? "";
                view.LastThought = live.LastThought ?? "";
                view.Mood = live.Mood;
                view.Money = live.Money;
                view.Relationships = live.Relationships is { Count: > 0 }
                    ? live.Relationships
                    : local?.Relationships ?? new Dictionary<string, double>();
            }
            else
            {
                view.Location = local?.Home ?? "";
                view.Relationships = local?.Relationships ?? new Dictionary<string, double>();
            }

            return view;
        }

        private static IEnumerable<string> RosterOrder(SimulationSession session)
        {
            var seen = new HashSet<string>();
            var order = new List<string>();

            void Add(string id)
            {
                if (!string.IsNullOrEmpty(id) && seen.Add(id))
                {
                    order.Add(id);
                }
            }

            if (session.Manifest?.Personas is { Count: > 0 } personas)
            {
                foreach (SimPersona persona in personas)
                {
                    Add(persona?.AgentId);
                }
            }
            else
            {
                foreach (LocalPersona persona in TownPersonas.All)
                {
                    Add(persona.AgentId);
                }
            }

            // Defensive: surface any live agent the roster did not enumerate.
            foreach (string id in session.Agents.Keys)
            {
                Add(id);
            }

            return order;
        }

        private static SimPersona FindManifestPersona(SimulationSession session, string agentId)
        {
            if (session.Manifest?.Personas == null)
            {
                return null;
            }

            foreach (SimPersona persona in session.Manifest.Personas)
            {
                if (persona != null && persona.AgentId == agentId)
                {
                    return persona;
                }
            }

            return null;
        }

        private static string FirstNonEmpty(params string[] candidates)
        {
            foreach (string candidate in candidates)
            {
                if (!string.IsNullOrEmpty(candidate))
                {
                    return candidate;
                }
            }

            return "";
        }
    }
}
