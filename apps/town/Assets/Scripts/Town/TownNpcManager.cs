using System.Collections.Generic;
using AgentTown.Simulation;
using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// Spawns and updates NPCs from <see cref="SimulationSession"/> positions (§7 NpcLayer, faithful
    /// port of the retired UE <c>TownNpcManager</c>). Reads the session's authoritative Unity
    /// positions and adds the §6.5 visual spawn offset (§4.3 step 4) so co-located residents don't
    /// stack — offset only, never written back to the backend.
    ///
    /// <para>Live and Replay/Offline both drive <c>NavMeshAgent.SetDestination</c> (seed still
    /// warps). Replay paces agent speed to the playhead step. Colours are assigned
    /// deterministically on first sight via <see cref="TownPalette"/>.</para>
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class TownNpcManager : MonoBehaviour
    {
        private readonly Dictionary<string, TownNpc> npcs = new();
        private readonly Dictionary<string, int> colorIndices = new();

        private SimulationSession session;
        private Material sharedMaterial;
        private Transform container;

        /// <summary>Point the manager at a session (defaults to the singleton) and its NPC material.</summary>
        public void Bind(SimulationSession target, Material npcMaterial)
        {
            Unsubscribe();
            session = target;
            sharedMaterial = npcMaterial;
            Subscribe();
            SyncNpcs();
        }

        private void OnEnable()
        {
            session ??= SimulationSession.Instance;
            Subscribe();
            SyncNpcs();
        }

        private void OnDisable() => Unsubscribe();

        private void Subscribe()
        {
            if (session != null)
            {
                session.OnSnapshotApplied += SyncNpcs;
                session.OnSelectionChanged += SyncNameplates;
            }
        }

        private void Unsubscribe()
        {
            if (session != null)
            {
                session.OnSnapshotApplied -= SyncNpcs;
                session.OnSelectionChanged -= SyncNameplates;
            }
        }

        /// <summary>
        /// Seed NPCs at their home region anchors before the first snapshot (mirrors Desktop
        /// <c>seedTownSpawnsIfNeeded</c>) so the town is populated on arrival. Live/replay snapshots
        /// then take over via <see cref="SyncNpcs"/>.
        /// </summary>
        public void SeedFromPersonas(IReadOnlyDictionary<string, Vector3> regionAnchors)
        {
            if (regionAnchors == null)
            {
                return;
            }

            foreach (LocalPersona persona in TownPersonas.All)
            {
                if (string.IsNullOrEmpty(persona.Home) || !regionAnchors.TryGetValue(persona.Home, out Vector3 anchor))
                {
                    continue;
                }

                Vector3 spawn = anchor + TownPersonas.UnitySpawnOffset(persona.AgentId);
                TownNpc npc = GetOrCreate(persona.AgentId);
                npc.ApplyGoal(spawn, snap: true);
                string subtitle = AgentDisplayLabels.FormatNameplateSubtitle(
                    persona.Role,
                    includeMood: false,
                    mood: 0,
                    activityFallback: persona.Goal ?? "");
                npc.SetNameplate(persona.Name, subtitle, selected: false);
            }
        }

        private void SyncNpcs()
        {
            if (session == null)
            {
                return;
            }

            IReadOnlyDictionary<string, Vector3> positions = session.AgentUnityPositions;
            // No snapshot yet — keep any seeded NPCs rather than tearing them down.
            if (positions.Count == 0)
            {
                return;
            }

            // Seed still warps; snapshot sync never whole-frame teleports — Live + Replay/Offline
            // both path (or Transform-lerp fallback). Replay paces speed to playhead step window.
            // Headless shoot may call SnapAllToGoals after a landmark seek so overlays land on cue.
            bool paceToTick = !session.IsLive;
            float playbackSpeed = session.PlaybackSpeed;
            float stepSeconds = SimulationSession.PlaybackStepSeconds;
            var seen = new HashSet<string>();

            foreach (KeyValuePair<string, Vector3> pair in positions)
            {
                seen.Add(pair.Key);
                Vector3 target = pair.Value + TownPersonas.UnitySpawnOffset(pair.Key);
                TownNpc npc = GetOrCreate(pair.Key);
                npc.ApplyGoal(
                    target,
                    snap: false,
                    paceToTick: paceToTick,
                    playbackSpeed: playbackSpeed,
                    stepSeconds: stepSeconds);
            }

            RemoveStale(seen);
            SyncNameplates();
        }

        /// <summary>
        /// Instantly place every live NPC on its current snapshot goal (no pathing).
        /// Used by headless shoot after seeking a landmark interaction tick.
        /// </summary>
        public void SnapAllToGoals()
        {
            if (session == null)
            {
                return;
            }

            IReadOnlyDictionary<string, Vector3> positions = session.AgentUnityPositions;
            if (positions.Count == 0)
            {
                return;
            }

            foreach (KeyValuePair<string, Vector3> pair in positions)
            {
                Vector3 target = pair.Value + TownPersonas.UnitySpawnOffset(pair.Key);
                TownNpc npc = GetOrCreate(pair.Key);
                npc.ApplyGoal(target, snap: true);
            }

            SyncNameplates();
        }

        private void SyncNameplates()
        {
            if (session == null)
            {
                return;
            }

            string selectedId = session.SelectedAgentId;
            foreach (KeyValuePair<string, TownNpc> pair in npcs)
            {
                TownNpc npc = pair.Value;
                if (npc == null)
                {
                    continue;
                }

                string name = pair.Key;
                string role = "";
                string activity = "";
                bool includeMood = false;
                double mood = 0;

                if (session.Agents.TryGetValue(pair.Key, out SimAgentState state) && state != null)
                {
                    name = string.IsNullOrEmpty(state.Name) ? pair.Key : state.Name;
                    role = state.Role ?? "";
                    activity = !string.IsNullOrEmpty(state.Activity)
                        ? state.Activity
                        : state.Goal ?? "";
                    includeMood = true;
                    mood = state.Mood;
                }
                else
                {
                    foreach (LocalPersona persona in TownPersonas.All)
                    {
                        if (persona.AgentId == pair.Key)
                        {
                            name = persona.Name;
                            role = persona.Role ?? "";
                            activity = persona.Goal ?? "";
                            break;
                        }
                    }
                }

                // Live may omit role — fall back to persona roster without inventing mood.
                if (string.IsNullOrEmpty(role))
                {
                    LocalPersona roster = TownPersonas.Get(pair.Key);
                    if (roster != null && !string.IsNullOrEmpty(roster.Role))
                    {
                        role = roster.Role;
                    }
                }

                string subtitle = AgentDisplayLabels.FormatNameplateSubtitle(
                    role,
                    includeMood,
                    mood,
                    activityFallback: activity);
                npc.SetNameplate(name, subtitle, pair.Key == selectedId);
            }
        }

        private TownNpc GetOrCreate(string agentId)
        {
            if (npcs.TryGetValue(agentId, out TownNpc existing) && existing != null)
            {
                return existing;
            }

            EnsureContainer();

            var go = new GameObject($"NPC_{agentId}");
            go.transform.SetParent(container, false);

            var npc = go.AddComponent<TownNpc>();
            npc.Initialize(agentId, sharedMaterial);
            if (AgentTown.Show.ShowCast.TryGetColor(agentId, out Color castColor))
            {
                npc.ApplyTint(castColor);
            }
            else
            {
                npc.ApplyTint(TownPalette.NpcColor(ColorIndexFor(agentId)));
            }

            npcs[agentId] = npc;
            return npc;
        }

        private int ColorIndexFor(string agentId)
        {
            if (!colorIndices.TryGetValue(agentId, out int index))
            {
                index = colorIndices.Count;
                colorIndices[agentId] = index;
            }

            return index;
        }

        private void RemoveStale(HashSet<string> seen)
        {
            var stale = new List<string>();
            foreach (KeyValuePair<string, TownNpc> pair in npcs)
            {
                if (!seen.Contains(pair.Key))
                {
                    stale.Add(pair.Key);
                    if (pair.Value != null)
                    {
                        Destroy(pair.Value.gameObject);
                    }
                }
            }

            foreach (string id in stale)
            {
                npcs.Remove(id);
            }
        }

        /// <summary>Live NPC for <paramref name="agentId"/> if spawned.</summary>
        public bool TryGetNpc(string agentId, out TownNpc npc)
        {
            npc = null;
            if (string.IsNullOrEmpty(agentId))
            {
                return false;
            }

            return npcs.TryGetValue(agentId, out npc) && npc != null;
        }

        /// <summary>
        /// Prefer the living NPC transform (smooth path / soft-move). Falls back to session
        /// snapshot + spawn offset when the NPC is not spawned yet.
        /// </summary>
        public bool TryGetLiveWorldPosition(string agentId, out Vector3 worldPos)
        {
            worldPos = default;
            if (TryGetNpc(agentId, out TownNpc npc))
            {
                worldPos = npc.transform.position;
                return true;
            }

            if (session != null
                && session.AgentUnityPositions.TryGetValue(agentId, out Vector3 wirePos))
            {
                worldPos = wirePos + TownPersonas.UnitySpawnOffset(agentId);
                return true;
            }

            return false;
        }

        private void EnsureContainer()
        {
            if (container == null)
            {
                container = new GameObject("NPCs").transform;
                container.SetParent(transform, false);
            }
        }
    }
}
