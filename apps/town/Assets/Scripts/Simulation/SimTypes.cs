using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace AgentTown.Simulation
{
    // ---------------------------------------------------------------------------
    // Wire types — hand-aligned with agentcore.simulation.types + OpenAPI (§6.1).
    // Newtonsoft populates public fields by name; missing/extra fields are tolerated.
    // ---------------------------------------------------------------------------

    /// <summary>Per-agent snapshot on <c>sim.agent_state</c> and inside tick snapshots.</summary>
    public sealed class SimAgentState
    {
        [JsonProperty("agent_id")] public string AgentId = "";
        [JsonProperty("name")] public string Name = "";
        [JsonProperty("role")] public string Role = "";
        [JsonProperty("location")] public string Location = "";
        [JsonProperty("position")] public WireVec3 Position;
        [JsonProperty("activity")] public string Activity = "";
        [JsonProperty("mood")] public double Mood;
        [JsonProperty("goal")] public string Goal = "";
        [JsonProperty("last_thought")] public string LastThought = "";
        [JsonProperty("relationships")] public Dictionary<string, double> Relationships = new();
        [JsonProperty("tick_memories")] public List<string> TickMemories = new();
        [JsonProperty("money")] public double Money = 100.0;
        [JsonProperty("inventory")] public Dictionary<string, int> Inventory = new();
    }

    public sealed class TownGovernanceState
    {
        [JsonProperty("last_motion")] public string LastMotion;
        [JsonProperty("last_outcome")] public string LastOutcome;
        [JsonProperty("yes_votes")] public int YesVotes;
        [JsonProperty("no_votes")] public int NoVotes;
        [JsonProperty("abstain_votes")] public int AbstainVotes;
        [JsonProperty("policies")] public List<string> Policies = new();
    }

    public sealed class WorldModifiers
    {
        [JsonProperty("market_price_multiplier")] public double MarketPriceMultiplier = 1.0;
        [JsonProperty("storm_active")] public bool StormActive;
        [JsonProperty("festival_active")] public bool FestivalActive;
        [JsonProperty("square_attraction_boost")] public double SquareAttractionBoost;
    }

    public sealed class WorldEvent
    {
        [JsonProperty("event_id")] public string EventId = "";
        [JsonProperty("kind")] public string Kind = "";
        [JsonProperty("event_type")] public string EventType = "";
        [JsonProperty("title")] public string Title = "";
        [JsonProperty("description")] public string Description = "";
        [JsonProperty("payload")] public JObject Payload;
        [JsonProperty("tick_started")] public int TickStarted;
        [JsonProperty("duration_ticks")] public int DurationTicks = 1;
        [JsonProperty("source")] public string Source = "scheduler";
    }

    /// <summary>Macro indicators for one tick (optional on tick snapshots — §6.7).</summary>
    public sealed class TickMetrics
    {
        [JsonProperty("tick")] public int Tick;
        [JsonProperty("hour")] public int Hour;
        [JsonProperty("avg_mood")] public double AvgMood;
        [JsonProperty("trade_count")] public int TradeCount;
        [JsonProperty("trade_total_amount")] public double TradeTotalAmount;
        [JsonProperty("positive_relation_ratio")] public double PositiveRelationRatio;
        [JsonProperty("population_by_region")] public Dictionary<string, int> PopulationByRegion = new();
    }

    /// <summary>Persisted world frame for a single tick (<c>GET /ticks/{n}</c> source of truth).</summary>
    public sealed class SimTickSnapshot
    {
        [JsonProperty("tick")] public int Tick;
        [JsonProperty("hour")] public int Hour;
        [JsonProperty("agents")] public Dictionary<string, SimAgentState> Agents = new();
        [JsonProperty("event_log")] public List<string> EventLog = new();
        [JsonProperty("governance")] public TownGovernanceState Governance = new();
        [JsonProperty("active_events")] public List<WorldEvent> ActiveEvents = new();
        [JsonProperty("modifiers")] public WorldModifiers Modifiers = new();
        [JsonProperty("metrics")] public TickMetrics Metrics;
    }

    // ---- Manifest — authoritative roster from GET /manifest (§6.4) ----

    public sealed class BigFive
    {
        [JsonProperty("openness")] public double Openness = 0.5;
        [JsonProperty("conscientiousness")] public double Conscientiousness = 0.5;
        [JsonProperty("extraversion")] public double Extraversion = 0.5;
        [JsonProperty("agreeableness")] public double Agreeableness = 0.5;
        [JsonProperty("neuroticism")] public double Neuroticism = 0.5;
    }

    public sealed class SimPersona
    {
        [JsonProperty("agent_id")] public string AgentId = "";
        [JsonProperty("name")] public string Name = "";
        [JsonProperty("role")] public string Role = "";
        [JsonProperty("location")] public string Location = "";
        [JsonProperty("goal")] public string Goal = "";
        [JsonProperty("system_prompt")] public string SystemPrompt = "";
        [JsonProperty("big_five")] public BigFive BigFive = new();
        [JsonProperty("goals_stack")] public List<string> GoalsStack = new();
    }

    public sealed class RunManifest
    {
        [JsonProperty("manifest_version")] public string ManifestVersion = "";
        [JsonProperty("scenario")] public string Scenario = "town";
        [JsonProperty("seed")] public int Seed;
        [JsonProperty("personas")] public List<SimPersona> Personas = new();
        [JsonProperty("regions")] public List<string> Regions = new();
        [JsonProperty("temperature")] public double Temperature = 0.8;
        [JsonProperty("created_at")] public string CreatedAt;
        [JsonProperty("code_version")] public string CodeVersion;
    }

    // ---- REST response envelopes (§5) ----

    public sealed class SimulationRunSummary
    {
        [JsonProperty("id")] public string Id = "";
        [JsonProperty("scenario")] public string Scenario = "town";
        [JsonProperty("seed")] public int Seed;
        [JsonProperty("status")] public string Status = "";
        [JsonProperty("current_tick")] public int CurrentTick;
    }

    public sealed class SimulationRunStatusResponse
    {
        [JsonProperty("run_id")] public string RunId = "";
        [JsonProperty("status")] public string Status = "";
        [JsonProperty("current_tick")] public int CurrentTick;
    }

    public sealed class AdvanceTickResponse
    {
        [JsonProperty("run_id")] public string RunId = "";
        [JsonProperty("snapshot")] public SimTickSnapshot Snapshot = new();
    }

    public sealed class SimTickFrameResponse
    {
        [JsonProperty("run_id")] public string RunId = "";
        [JsonProperty("tick_number")] public int TickNumber;
        [JsonProperty("snapshot")] public SimTickSnapshot Snapshot = new();
    }

    public sealed class SimulationRunManifestResponse
    {
        [JsonProperty("run_id")] public string RunId = "";
        [JsonProperty("manifest")] public RunManifest Manifest = new();
    }

    public sealed class SimulationRunMetricsResponse
    {
        [JsonProperty("run_id")] public string RunId = "";
        [JsonProperty("metrics")] public List<TickMetrics> Metrics = new();
    }

    public sealed class InjectSimulationEventResponse
    {
        [JsonProperty("run_id")] public string RunId = "";
        [JsonProperty("event_id")] public string EventId = "";
        [JsonProperty("event_type")] public string EventType = "";
        [JsonProperty("title")] public string Title = "";
        [JsonProperty("queued_for_tick")] public int QueuedForTick;
    }

    // ---- SSE + client-side view types ----

    /// <summary>One decoded SSE envelope (<c>{ type, payload, timestamp }</c>).</summary>
    public sealed class SimSseEvent
    {
        [JsonProperty("type")] public string Type = "";
        [JsonProperty("payload")] public JObject Payload;
        [JsonProperty("timestamp")] public string Timestamp = "";
    }

    /// <summary>One decision row derived from <c>sim.agent_action</c> (decisions panel).</summary>
    public sealed class SimDecision
    {
        public int Tick;
        public string AgentId = "";
        public string Summary = "";
        public string ActionType = "";
        public string Location = "";
    }

    /// <summary>One event-timeline row derived from a <c>sim.*</c> event (tick_frame excluded).</summary>
    public sealed class SimTickEvent
    {
        public int Tick;
        public string Type = "";
        public string AgentId = "";
        public string Summary = "";
        /// <summary>Optional multi-line body (e.g. conversation transcript) under the summary.</summary>
        public string Detail = "";
        public string Timestamp = "";
    }
}
