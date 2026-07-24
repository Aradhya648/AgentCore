using System.Collections.Generic;
using System.Threading.Tasks;
using AgentTown.Simulation;
using Newtonsoft.Json;
using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>Wire XZ nudge (wire space) so co-located NPCs don't stack (§6.5).</summary>
    public sealed class PersonaOffset
    {
        [JsonProperty("x")] public double X;
        [JsonProperty("z")] public double Z;
    }

    /// <summary>
    /// Local persona card — the §6.4 fallback authoring source (exported from Desktop
    /// <c>townPersonas.ts</c>). Supplies <c>bio</c> / relationships that the backend manifest does
    /// not yet carry, plus the §6.5 spawn offset table.
    /// </summary>
    public sealed class LocalPersona
    {
        [JsonProperty("agent_id")] public string AgentId = "";
        [JsonProperty("name")] public string Name = "";
        [JsonProperty("role")] public string Role = "";
        [JsonProperty("home")] public string Home = "";
        [JsonProperty("bio")] public string Bio = "";
        [JsonProperty("goal")] public string Goal = "";
        [JsonProperty("big_five")] public BigFive BigFive = new();
        [JsonProperty("relationships")] public Dictionary<string, double> Relationships = new();
        [JsonProperty("spawn_offset")] public PersonaOffset SpawnOffset = new();
    }

    public sealed class LocalPersonaFile
    {
        [JsonProperty("personas")] public List<LocalPersona> Personas = new();
    }

    /// <summary>
    /// Process-wide store of the local persona cards + spawn offsets (§6.4, §6.5). Loaded once from
    /// <c>StreamingAssets/town-personas.json</c> (WebGL-safe via <see cref="StreamingAssetsText"/>).
    /// NPC layer and UI read from here; it never touches the backend contract.
    /// </summary>
    public static class TownPersonas
    {
        public const string FileName = "town-personas.json";

        private static readonly Dictionary<string, LocalPersona> ById = new();
        private static readonly List<LocalPersona> Ordered = new();

        public static bool Loaded { get; private set; }

        public static IReadOnlyList<LocalPersona> All => Ordered;

        public static LocalPersona Get(string agentId) =>
            agentId != null && ById.TryGetValue(agentId, out LocalPersona persona) ? persona : null;

        /// <summary>Per-agent visual spawn offset already transformed to Unity space (x, 0, -z per §6.2/§6.5).</summary>
        public static Vector3 UnitySpawnOffset(string agentId)
        {
            LocalPersona persona = Get(agentId);
            if (persona?.SpawnOffset == null)
            {
                return Vector3.zero;
            }

            return new Vector3((float)persona.SpawnOffset.X, 0f, (float)(-persona.SpawnOffset.Z));
        }

        public static async Task LoadAsync()
        {
            if (Loaded)
            {
                return;
            }

            string json = await StreamingAssetsText.LoadAsync(FileName);
            Populate(json);
            Loaded = true;
        }

        /// <summary>Parse + index a persona file. Exposed for EditMode tests / re-seeding.</summary>
        public static void Populate(string json)
        {
            ById.Clear();
            Ordered.Clear();

            if (!SimJson.TryDeserialize<LocalPersonaFile>(json, out LocalPersonaFile file) || file.Personas == null)
            {
                Debug.LogWarning("[AgentTown] TownPersonas: failed to load local personas");
                return;
            }

            IndexPersonas(file.Personas);
        }

        /// <summary>EditMode helper: seed personas without going through JSON.</summary>
        internal static void PopulateForTests(IReadOnlyList<LocalPersona> personas)
        {
            ById.Clear();
            Ordered.Clear();
            IndexPersonas(personas);
            Loaded = true;
        }

        private static void IndexPersonas(IReadOnlyList<LocalPersona> personas)
        {
            if (personas == null)
            {
                return;
            }

            foreach (LocalPersona persona in personas)
            {
                if (persona == null || string.IsNullOrEmpty(persona.AgentId))
                {
                    continue;
                }

                persona.BigFive ??= new BigFive();
                persona.Relationships ??= new Dictionary<string, double>();
                persona.SpawnOffset ??= new PersonaOffset();
                ById[persona.AgentId] = persona;
                Ordered.Add(persona);
            }
        }
    }
}
