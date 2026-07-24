using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Client-side session state — the single source of truth for UI + 3D (UT-01). Faithful
    /// port of the retired UE <c>FSimulationSession</c>, adapted to async/await + Unity.
    /// Implements the §4 state fields, §4.2 mode rules, §4.3 ApplySnapshot pipeline and the
    /// §6.6 SSE event table (including ignoring <c>sim.tick_frame</c>).
    ///
    /// <para><b>Live vs Replay</b> (§4.2): Live consumes SSE and, on <c>tick_ended</c>, pulls
    /// the frame via <c>GET /ticks/{n}</c> (never applies the advance response snapshot
    /// directly). Replay ignores world-state SSE and only pulls frames via GET.</para>
    ///
    /// <para>Drive it from a MonoBehaviour: call <see cref="Update"/> each frame (it polls the
    /// SSE queue and advances playback). All public mutators must be called on the main thread.</para>
    /// </summary>
    public sealed class SimulationSession
    {
        public enum ClientMode
        {
            Live,
            Replay,
            Offline,
        }

        private const int MaxDecisions = 50;
        private const int MaxTickEvents = 400;
        /// <summary>Seconds between playhead steps at 1x (NPC pace + UpdatePlayback share this).</summary>
        public const float PlaybackStepSeconds = 0.6f;

        private const float BasePlaybackStepSec = PlaybackStepSeconds;
        private const int MinPlaybackTick = 1;
        private const string OfflineRunId = OfflineDemoPack.DemoRunId;

        private static SimulationSession instance;

        /// <summary>Process-wide singleton (mirrors the UE reference). Tests may also <c>new</c> a fresh instance.</summary>
        public static SimulationSession Instance => instance ??= new SimulationSession();

        private readonly SimulationRestClient rest = new();
        private readonly SimulationSseClient sse = new();

        private Dictionary<string, SimAgentState> agents = new();
        private readonly Dictionary<string, Vector3> agentUnityPositions = new();
        private readonly Dictionary<int, SimTickSnapshot> tickCache = new();
        private readonly List<SimDecision> decisions = new();
        private readonly List<SimTickEvent> tickEvents = new();
        private readonly Dictionary<string, ActiveInteraction> activeInteractions = new();
        private readonly Dictionary<int, List<ActiveInteraction>> offlineInteractionsByTick = new();

        private WorldModifiers modifiers = new();
        private TickMetrics metrics;
        private List<WorldEvent> activeEvents = new();

        private string apiBase = "";
        private string accessToken = "";
        private bool ticking;
        private bool playing;
        private int seekGeneration;
        private float playbackAccumulator;
        private string selectedAgentId;
        private string trackedAgentId;

        public SimulationSession()
        {
            sse.OnEvent += HandleSseEvent;
            sse.OnStreamStatusChanged += HandleStreamStatus;
        }

        // ---- §4.1 state fields ----

        public ClientMode Mode { get; private set; } = ClientMode.Live;
        public string RunId { get; private set; } = "";
        public string Scenario { get; private set; } = "town";
        /// <summary>Active offline story pack (<see cref="DemoPackIds"/>); empty when not Offline.</summary>
        public string OfflinePackId { get; private set; } = "";
        public string Status { get; private set; } = "";
        public string StatusMessage { get; private set; } = "";
        public int Tick { get; private set; }
        public int Hour { get; private set; }
        public bool Ticking => ticking;
        public int? Playhead { get; private set; }
        public bool Playing => playing;
        public float PlaybackSpeed { get; private set; } = 1f;
        public RunManifest Manifest { get; private set; } = new();
        public string StreamStatus => sse.StreamStatus;
        public string SelectedAgentId => selectedAgentId;
        public string TrackedAgentId => trackedAgentId;

        public IReadOnlyDictionary<string, SimAgentState> Agents => agents;
        public IReadOnlyDictionary<string, Vector3> AgentUnityPositions => agentUnityPositions;
        public IReadOnlyList<SimDecision> Decisions => decisions;
        public IReadOnlyList<SimTickEvent> TickEvents => tickEvents;
        public IReadOnlyDictionary<int, SimTickSnapshot> TickCache => tickCache;
        public WorldModifiers Modifiers => modifiers;
        public TickMetrics Metrics => metrics;
        public IReadOnlyList<WorldEvent> ActiveEvents => activeEvents;
        public IReadOnlyDictionary<string, ActiveInteraction> ActiveInteractions => activeInteractions;

        /// <summary>
        /// Offline story pulses (conversation / trade / vote), tick-ascending.
        /// Empty when not Offline or pack has no interactions.
        /// </summary>
        public IReadOnlyList<ActiveInteraction> OfflineStoryInteractions
        {
            get
            {
                if (offlineInteractionsByTick.Count == 0)
                {
                    return Array.Empty<ActiveInteraction>();
                }

                var list = new List<ActiveInteraction>();
                foreach (KeyValuePair<int, List<ActiveInteraction>> pair in offlineInteractionsByTick)
                {
                    if (pair.Value == null)
                    {
                        continue;
                    }

                    foreach (ActiveInteraction ix in pair.Value)
                    {
                        if (ix != null)
                        {
                            list.Add(ix);
                        }
                    }
                }

                list.Sort((a, b) => a.Tick.CompareTo(b.Tick));
                return list;
            }
        }

        public int DisplayTick => Playhead ?? Tick;
        public bool IsOffline => Mode == ClientMode.Offline;
        public bool IsLive => Mode == ClientMode.Live && Playhead == null;
        /// <summary>Replay scrubbing OR offline demo playhead — both ignore live SSE world updates.</summary>
        public bool IsReplayActive => Mode == ClientMode.Replay || Mode == ClientMode.Offline || Playhead != null;

        // ---- events (UI + 3D subscribe) ----

        public event Action OnSnapshotApplied;
        public event Action<string> OnStatusChanged;
        public event Action OnPlaybackChanged;
        public event Action OnDecisionsChanged;
        public event Action OnEventsChanged;
        public event Action OnSelectionChanged;
        public event Action OnInteractionsChanged;

        // ---- lifecycle ----

        public void Configure(string apiBaseUrl, string token, string initialRunId = "")
        {
            apiBase = TrimTrailingSlashes(apiBaseUrl ?? "");
            accessToken = token ?? "";
            rest.Configure(apiBase, accessToken);
            sse.Configure(apiBase, accessToken, initialRunId ?? "");

            if (!string.IsNullOrEmpty(initialRunId))
            {
                RunId = initialRunId;
                SetStatusMessage($"Resuming run {RunId}");
            }
            else
            {
                SetStatusMessage($"API: {apiBase}");
            }
        }

        public void Reset()
        {
            DisconnectStream();

            Mode = ClientMode.Live;
            RunId = "";
            Scenario = "town";
            OfflinePackId = "";
            Status = "";
            Tick = 0;
            Hour = 0;
            ticking = false;
            Playhead = null;
            playing = false;
            PlaybackSpeed = 1f;
            seekGeneration = 0;
            playbackAccumulator = 0f;
            agents = new Dictionary<string, SimAgentState>();
            agentUnityPositions.Clear();
            tickCache.Clear();
            decisions.Clear();
            tickEvents.Clear();
            activeInteractions.Clear();
            offlineInteractionsByTick.Clear();
            modifiers = new WorldModifiers();
            metrics = null;
            activeEvents = new List<WorldEvent>();
            Manifest = new RunManifest();
            selectedAgentId = null;
            trackedAgentId = null;

            SetStatusMessage("Session reset");
            NotifyPlaybackChanged();
            OnInteractionsChanged?.Invoke();
        }

        /// <summary>Per-frame pump: drain SSE queue then advance auto-playback. Call from MonoBehaviour.Update.</summary>
        public void Update(float deltaTime)
        {
            sse.Poll();
            PruneExpiredInteractions();
            UpdatePlayback(deltaTime);
        }

        // ---- §4.3 ApplySnapshot ----

        public void ApplySnapshot(SimTickSnapshot snapshot)
        {
            if (snapshot == null)
            {
                return;
            }

            Tick = snapshot.Tick;
            Hour = snapshot.Hour;

            // Copy (Dictionary assignment aliases; a copy keeps the cached frame immutable).
            agents = snapshot.Agents != null
                ? new Dictionary<string, SimAgentState>(snapshot.Agents)
                : new Dictionary<string, SimAgentState>();

            agentUnityPositions.Clear();
            foreach (KeyValuePair<string, SimAgentState> pair in agents)
            {
                WireVec3 wire = pair.Value != null ? pair.Value.Position : default;
                agentUnityPositions[pair.Key] = WireCoordinateTransform.ToUnity(wire);
            }

            modifiers = snapshot.Modifiers ?? new WorldModifiers();
            metrics = snapshot.Metrics;
            activeEvents = snapshot.ActiveEvents != null
                ? new List<WorldEvent>(snapshot.ActiveEvents)
                : new List<WorldEvent>();

            CacheSnapshot(snapshot.Tick, snapshot);
            SyncOfflineInteractionsForTick(snapshot.Tick);

            string modeLabel = IsOffline
                ? $"离线演示 · 无需后端 · {DemoPackIds.DisplayName(OfflinePackId)}"
                : IsReplayActive ? "Replay" : "Live";
            SetStatusMessage($"{modeLabel} — Tick {Tick} (hour {Hour}) — {agents.Count} agents");
            OnSnapshotApplied?.Invoke();
        }

        /// <summary>
        /// Enter client-local offline / demo mode: no REST/SSE, frames from
        /// <see cref="OfflineDemoBuilder"/>. Shares <see cref="ApplySnapshot"/> and playhead
        /// playback with Replay. Does not change backend API contracts.
        /// </summary>
        public void EnterOfflineDemo(OfflineDemoPack pack)
        {
            if (pack == null || pack.Frames == null || pack.Frames.Count == 0)
            {
                SetStatusMessage("离线演示失败：无可用帧");
                return;
            }

            DisconnectStream();

            Mode = ClientMode.Offline;
            RunId = string.IsNullOrEmpty(pack.RunId) ? OfflineRunId : pack.RunId;
            OfflinePackId = DemoPackIds.Normalize(pack.PackId);
            Scenario = pack.Manifest?.Scenario ?? "town";
            Status = "offline";
            ticking = false;
            playing = false;
            PlaybackSpeed = 1f;
            seekGeneration++;
            playbackAccumulator = 0f;
            agents = new Dictionary<string, SimAgentState>();
            agentUnityPositions.Clear();
            tickCache.Clear();
            decisions.Clear();
            tickEvents.Clear();
            activeInteractions.Clear();
            offlineInteractionsByTick.Clear();
            modifiers = new WorldModifiers();
            metrics = null;
            activeEvents = new List<WorldEvent>();
            Manifest = pack.Manifest ?? new RunManifest();
            selectedAgentId = null;
            trackedAgentId = null;

            foreach (SimTickSnapshot frame in pack.Frames)
            {
                if (frame == null)
                {
                    continue;
                }

                CacheSnapshot(frame.Tick, frame);
            }

            if (pack.Interactions != null)
            {
                foreach (ActiveInteraction ix in pack.Interactions)
                {
                    if (ix == null)
                    {
                        continue;
                    }

                    if (!offlineInteractionsByTick.TryGetValue(ix.Tick, out List<ActiveInteraction> list))
                    {
                        list = new List<ActiveInteraction>();
                        offlineInteractionsByTick[ix.Tick] = list;
                    }

                    list.Add(ix);
                }
            }

            if (pack.Decisions != null)
            {
                foreach (SimDecision decision in pack.Decisions)
                {
                    if (decision != null)
                    {
                        decisions.Add(decision);
                    }
                }

                while (decisions.Count > MaxDecisions)
                {
                    decisions.RemoveAt(decisions.Count - 1);
                }
            }

            if (pack.Events != null)
            {
                foreach (SimTickEvent evt in pack.Events)
                {
                    if (evt != null)
                    {
                        tickEvents.Add(evt);
                    }
                }

                while (tickEvents.Count > MaxTickEvents)
                {
                    tickEvents.RemoveAt(tickEvents.Count - 1);
                }
            }

            int firstTick = pack.Frames[0].Tick;
            int lastTick = pack.Frames[pack.Frames.Count - 1].Tick;
            for (int i = 0; i < pack.Frames.Count; i++)
            {
                SimTickSnapshot frame = pack.Frames[i];
                if (frame != null && frame.Tick > lastTick)
                {
                    lastTick = frame.Tick;
                }
            }

            Playhead = firstTick;
            NotifyPlaybackChanged();
            OnDecisionsChanged?.Invoke();
            OnEventsChanged?.Invoke();
            OnSelectionChanged?.Invoke();
            OnInteractionsChanged?.Invoke();

            if (tickCache.TryGetValue(firstTick, out SimTickSnapshot first))
            {
                ApplySnapshot(first);
            }

            // ApplySnapshot overwrites Tick with the viewed frame; keep the demo tail for UI / playback.
            Tick = lastTick;
            string packLabel = DemoPackIds.DisplayName(OfflinePackId);
            SetStatusMessage(
                $"离线演示 · 无需后端 — {packLabel} — Tick {Playhead} / {Tick} — {agents.Count} agents");
        }

        // ---- run control (§5) ----

        public async Task<bool> CreateRunAsync()
        {
            SetStatusMessage("Creating run…");
            SimulationRunSummary summary = await rest.CreateRunAsync(Scenario);
            if (summary == null)
            {
                SetStatusMessage($"Create run failed: {rest.LastError}");
                return false;
            }

            RunId = summary.Id;
            Status = summary.Status;
            Scenario = string.IsNullOrEmpty(summary.Scenario) ? Scenario : summary.Scenario;
            Tick = summary.CurrentTick;
            Hour = 0;
            Mode = ClientMode.Live;
            Playhead = null;
            playing = false;
            agents = new Dictionary<string, SimAgentState>();
            agentUnityPositions.Clear();
            tickCache.Clear();
            decisions.Clear();
            tickEvents.Clear();
            activeInteractions.Clear();
            offlineInteractionsByTick.Clear();
            modifiers = new WorldModifiers();
            metrics = null;
            activeEvents = new List<WorldEvent>();
            Manifest = new RunManifest();
            NotifyPlaybackChanged();
            OnInteractionsChanged?.Invoke();

            SetStatusMessage($"Run {RunId} created (tick {Tick})");
            OnSnapshotApplied?.Invoke();

            await BootstrapActiveRunAsync();
            RememberLocalHistory(summary.Seed);
            return true;
        }

        public async Task<bool> AdvanceTickAsync()
        {
            if (IsOffline)
            {
                SetStatusMessage("离线演示 — 无后端 Tick");
                return false;
            }

            if (string.IsNullOrEmpty(RunId))
            {
                SetStatusMessage("No run — create a run first");
                return false;
            }

            if (IsReplayActive)
            {
                await GoLiveAsync();
            }

            ticking = true;
            SetStatusMessage("Advancing tick…");

            // Per §4.2 we do NOT apply the advance response snapshot directly — the Live
            // frame arrives via SSE tick_ended → GET /ticks/{n}.
            AdvanceTickResponse result = await rest.AdvanceTickAsync(RunId);
            if (result == null)
            {
                ticking = false;
                SetStatusMessage($"Advance tick failed: {rest.LastError}");
                return false;
            }

            SetStatusMessage("Waiting for tick to complete…");
            return true;
        }

        public async Task<bool> LoadTickAsync(int tickNumber)
        {
            EnterReplay(tickNumber);
            ticking = true;
            SetStatusMessage($"Loading tick {tickNumber}…");
            bool ok = await FetchAndApplyTickAsync(tickNumber, updatePlayhead: true);
            ticking = false;
            return ok;
        }

        public Task<bool> FetchLiveTickAsync(int tickNumber)
        {
            Mode = ClientMode.Live;
            Playhead = null;
            NotifyPlaybackChanged();
            return FetchAndApplyTickAsync(tickNumber, updatePlayhead: false);
        }

        public async Task<bool> PauseRunAsync()
        {
            if (IsOffline || string.IsNullOrEmpty(RunId))
            {
                return false;
            }

            SimulationRunStatusResponse result = await rest.PauseRunAsync(RunId);
            if (result == null)
            {
                SetStatusMessage($"Pause failed: {rest.LastError}");
                return false;
            }

            Status = result.Status;
            SetStatusMessage($"Run paused (tick {result.CurrentTick})");
            NotifyPlaybackChanged();
            return true;
        }

        public async Task<bool> ResumeRunAsync()
        {
            if (IsOffline || string.IsNullOrEmpty(RunId))
            {
                return false;
            }

            SimulationRunStatusResponse result = await rest.ResumeRunAsync(RunId);
            if (result == null)
            {
                SetStatusMessage($"Resume failed: {rest.LastError}");
                return false;
            }

            Status = result.Status;
            SetStatusMessage($"Run resumed (tick {result.CurrentTick})");
            NotifyPlaybackChanged();
            return true;
        }

        /// <summary>POST inject — God Mode. Offline returns false with a status hint.</summary>
        public async Task<bool> InjectEventAsync(string eventType, string payloadJson = "{}")
        {
            if (IsOffline)
            {
                SetStatusMessage("离线演示 — 无法注入事件（需连接后端）");
                return false;
            }

            if (string.IsNullOrEmpty(RunId))
            {
                SetStatusMessage("No run — create a run first");
                return false;
            }

            InjectSimulationEventResponse result = await rest.InjectEventAsync(RunId, eventType, payloadJson);
            if (result == null)
            {
                SetStatusMessage($"Inject failed: {rest.LastError}");
                return false;
            }

            SetStatusMessage($"已注入：{result.Title}（Tick {result.QueuedForTick} 生效）");
            return true;
        }

        /// <summary>GET metrics series for the current run (optional HUD refresh).</summary>
        public async Task<SimulationRunMetricsResponse> FetchMetricsAsync()
        {
            if (IsOffline || string.IsNullOrEmpty(RunId))
            {
                return null;
            }

            return await rest.GetMetricsAsync(RunId);
        }

        /// <summary>
        /// Attach to an existing run by id (Run management "resume" — §11 SimulationRunManager).
        /// Additive helper composed from existing operations: clears the current run view (keeping
        /// the configured API/token), points at <paramref name="runId"/>, fetches the manifest,
        /// connects the live stream, and best-effort loads the first frame (live SSE then advances).
        /// Does not alter the §4.2 mode rules or §4.3 pipeline.
        /// </summary>
        public async Task<bool> AttachToRunAsync(string runId)
        {
            if (string.IsNullOrEmpty(runId))
            {
                SetStatusMessage("Enter a run id to resume");
                return false;
            }

            if (string.IsNullOrEmpty(apiBase))
            {
                SetStatusMessage("Configure API before resuming");
                return false;
            }

            Reset(); // clears run view + disconnects old stream; keeps apiBase/accessToken
            RunId = runId;
            SetStatusMessage($"Resuming run {runId}…");

            await BootstrapActiveRunAsync();
            await FetchLiveTickAsync(1);
            RememberLocalHistory(Manifest?.Seed);
            return true;
        }

        public async Task<bool> FetchManifestAsync()
        {
            if (string.IsNullOrEmpty(RunId))
            {
                return false;
            }

            SimulationRunManifestResponse result = await rest.GetManifestAsync(RunId);
            if (result == null)
            {
                SetStatusMessage($"Manifest failed: {rest.LastError}");
                return false;
            }

            Manifest = result.Manifest ?? new RunManifest();
            SetStatusMessage($"Manifest loaded — {Manifest.Personas.Count} residents");
            OnSnapshotApplied?.Invoke();
            return true;
        }

        public async Task BootstrapActiveRunAsync()
        {
            if (string.IsNullOrEmpty(RunId))
            {
                return;
            }

            await FetchManifestAsync();
            ConnectStream();
        }

        public void BootstrapActiveRun() => FireAndForget(BootstrapActiveRunAsync());

        // ---- playback (§4.2) ----

        public async Task GoLiveAsync()
        {
            seekGeneration++;
            playbackAccumulator = 0f;
            playing = false;

            if (IsOffline)
            {
                // Offline has no live stream — jump to the latest cached demo frame.
                int tail = HighestCachedTick();
                if (tail >= MinPlaybackTick && tickCache.TryGetValue(tail, out SimTickSnapshot last))
                {
                    Playhead = tail;
                    NotifyPlaybackChanged();
                    ApplySnapshot(last);
                }
                else
                {
                    NotifyPlaybackChanged();
                    SetStatusMessage("离线演示 — 无可用帧");
                }

                return;
            }

            Mode = ClientMode.Live;
            Playhead = null;
            NotifyPlaybackChanged();

            if (string.IsNullOrEmpty(RunId))
            {
                return;
            }

            if (Tick > 0)
            {
                await FetchAndApplyTickAsync(Tick, updatePlayhead: false);
            }
            else
            {
                SetStatusMessage("Live — waiting for first tick");
            }
        }

        public void GoLive() => FireAndForget(GoLiveAsync());

        public async Task SeekTickAsync(int targetTick)
        {
            if (string.IsNullOrEmpty(RunId))
            {
                return;
            }

            if (IsOffline)
            {
                SeekOfflineTick(targetTick);
                return;
            }

            if (targetTick >= Tick && Tick > 0)
            {
                await GoLiveAsync();
                return;
            }

            seekGeneration++;
            int generation = seekGeneration;
            EnterReplay(targetTick);

            if (tickCache.TryGetValue(targetTick, out SimTickSnapshot cached))
            {
                ApplySnapshot(cached);
                return;
            }

            bool ok = await FetchAndApplyTickAsync(targetTick, updatePlayhead: true);
            if (!ok || generation != seekGeneration)
            {
                // Superseded by a newer seek / go-live — drop this result.
            }
        }

        public void SeekTick(int targetTick) => FireAndForget(SeekTickAsync(targetTick));

        public void StepPlaybackTick(int delta)
        {
            SetPlaying(false);

            int tail = IsOffline ? HighestCachedTick() : Tick;
            int current = Playhead ?? tail;
            int next = current + delta;

            if (next < MinPlaybackTick)
            {
                return;
            }

            if (next > tail)
            {
                if (IsOffline)
                {
                    return;
                }

                GoLive();
                return;
            }

            if (!IsOffline && next >= Tick && Tick > 0)
            {
                GoLive();
                return;
            }

            SeekTick(next);
        }

        public void SetPlaying(bool value)
        {
            playing = value;
            if (!playing)
            {
                playbackAccumulator = 0f;
            }

            NotifyPlaybackChanged();
        }

        public void SetPlaybackSpeed(float speed)
        {
            PlaybackSpeed = speed;
            NotifyPlaybackChanged();
        }

        /// <summary>
        /// Offline / Replay: jump to the next story beat (interaction / world_event / vote),
        /// skipping <c>sim.tick_started</c> / <c>sim.tick_ended</c>. Pauses briefly so the
        /// cue is readable. Returns false when no later story tick exists.
        /// Live scripted does not maintain a local story index — use Advance Tick instead.
        /// </summary>
        public bool SeekNextStoryTick()
        {
            if (!IsOffline && Mode != ClientMode.Replay && Playhead == null)
            {
                SetStatusMessage("下一故事仅用于 Offline / Replay（Live 请推进 Tick）");
                return false;
            }

            int current = DisplayTick;
            int? next = FindNextStoryTick(current);
            if (next == null)
            {
                SetStatusMessage("已无后续故事节拍");
                return false;
            }

            SetPlaying(false);
            SeekTick(next.Value);
            SetStatusMessage($"下一故事 — Tick {next.Value}");
            return true;
        }

        /// <summary>
        /// Next tick &gt; <paramref name="afterTick"/> that carries an interaction, world_event,
        /// or vote (filters tick bookends). Exposed for EditMode tests.
        /// </summary>
        internal int? FindNextStoryTick(int afterTick)
        {
            int best = int.MaxValue;

            foreach (KeyValuePair<int, List<ActiveInteraction>> pair in offlineInteractionsByTick)
            {
                if (pair.Key > afterTick && pair.Key < best && pair.Value != null && pair.Value.Count > 0)
                {
                    best = pair.Key;
                }
            }

            for (int i = 0; i < tickEvents.Count; i++)
            {
                SimTickEvent evt = tickEvents[i];
                if (evt == null || evt.Tick <= afterTick)
                {
                    continue;
                }

                if (!SimEventFilters.IsStoryBeat(evt.Type))
                {
                    continue;
                }

                if (evt.Tick < best)
                {
                    best = evt.Tick;
                }
            }

            return best == int.MaxValue ? null : best;
        }

        public void UpdatePlayback(float deltaTime)
        {
            if (!playing || string.IsNullOrEmpty(RunId))
            {
                return;
            }

            playbackAccumulator += deltaTime;
            float interval = BasePlaybackStepSec / Mathf.Max(PlaybackSpeed, 0.1f);
            if (playbackAccumulator < interval)
            {
                return;
            }

            playbackAccumulator = 0f;

            int tail = IsOffline ? HighestCachedTick() : Tick;
            int current = Playhead ?? tail;
            int next = current + 1;

            if (next > tail)
            {
                SetPlaying(false);
                if (!IsOffline)
                {
                    GoLive();
                }

                return;
            }

            SeekTick(next);
        }

        // ---- selection ----

        public void SetSelectedAgent(string agentId)
        {
            selectedAgentId = agentId;
            OnSelectionChanged?.Invoke();
        }

        public void SetTrackedAgent(string agentId)
        {
            trackedAgentId = agentId;
            OnSelectionChanged?.Invoke();
        }

        // ---- internals ----

        private async Task<bool> FetchAndApplyTickAsync(int tickNumber, bool updatePlayhead)
        {
            if (string.IsNullOrEmpty(RunId))
            {
                SetStatusMessage("No run — create a run first");
                return false;
            }

            if (tickCache.TryGetValue(tickNumber, out SimTickSnapshot cached))
            {
                if (updatePlayhead && IsReplayActive)
                {
                    Playhead = tickNumber;
                    NotifyPlaybackChanged();
                }

                ApplySnapshot(cached);
                return true;
            }

            if (IsOffline)
            {
                SetStatusMessage($"离线演示 — 无 tick {tickNumber}");
                return false;
            }

            SimTickFrameResponse frame = await rest.GetTickSnapshotAsync(RunId, tickNumber);
            if (frame == null)
            {
                ticking = false;
                SetStatusMessage($"Load tick failed: {rest.LastError}");
                return false;
            }

            if (updatePlayhead && IsReplayActive)
            {
                Playhead = tickNumber;
                NotifyPlaybackChanged();
            }

            ApplySnapshot(frame.Snapshot);
            return true;
        }

        private void SeekOfflineTick(int targetTick)
        {
            int tail = HighestCachedTick();
            int clamped = Mathf.Clamp(targetTick, MinPlaybackTick, Mathf.Max(MinPlaybackTick, tail));
            if (!tickCache.TryGetValue(clamped, out SimTickSnapshot cached))
            {
                SetStatusMessage($"离线演示 — 无 tick {clamped}");
                return;
            }

            seekGeneration++;
            Playhead = clamped;
            NotifyPlaybackChanged();
            ApplySnapshot(cached);
            Tick = tail;
        }

        private int HighestCachedTick()
        {
            int max = 0;
            foreach (int key in tickCache.Keys)
            {
                if (key > max)
                {
                    max = key;
                }
            }

            return max;
        }

        private void ConnectStream()
        {
            if (string.IsNullOrEmpty(RunId) || IsOffline)
            {
                return;
            }

            sse.Configure(apiBase, accessToken, RunId);
            sse.Connect();
        }

        private void DisconnectStream() => sse.Disconnect();

        private void EnterReplay(int targetTick)
        {
            if (!IsOffline)
            {
                Mode = ClientMode.Replay;
            }

            Playhead = targetTick;
            if (!IsOffline)
            {
                activeInteractions.Clear();
                OnInteractionsChanged?.Invoke();
            }

            NotifyPlaybackChanged();
        }

        private void CacheSnapshot(int tickNumber, SimTickSnapshot snapshot) => tickCache[tickNumber] = snapshot;

        /// <summary>Public status line for boot / HUD (e.g.「正在加载小镇…」).</summary>
        public void SetStatusMessage(string message)
        {
            StatusMessage = message ?? "";
            OnStatusChanged?.Invoke(StatusMessage);
        }

        /// <summary>Persist to local Run history after create / resume success (§9 UT-10).</summary>
        private void RememberLocalHistory(int? seed)
        {
            if (string.IsNullOrEmpty(RunId))
            {
                return;
            }

            int? resolvedSeed = seed;
            if ((!resolvedSeed.HasValue || resolvedSeed.Value == 0) && Manifest != null && Manifest.Seed != 0)
            {
                resolvedSeed = Manifest.Seed;
            }

            LocalRunHistory.Remember(
                RunId,
                scenario: string.IsNullOrEmpty(Scenario) ? "town" : Scenario,
                seed: resolvedSeed,
                lastTick: Tick,
                status: Status);
        }

        private void NotifyPlaybackChanged() => OnPlaybackChanged?.Invoke();

        // ---- §6.6 SSE dispatch ----

        private void HandleSseEvent(SimSseEvent evt)
        {
            if (evt == null || string.IsNullOrEmpty(RunId))
            {
                return;
            }

            // §6.6: always ignore tick_frame to avoid a double path with tick_ended.
            if (evt.Type == "sim.tick_frame")
            {
                return;
            }

            // §4.2: in Replay / scrubbed playhead, ignore world-state-changing SSE.
            if (IsReplayActive)
            {
                return;
            }

            switch (evt.Type)
            {
                case "sim.tick_started":
                    HandleTickStarted(evt.Payload);
                    PushTickEvent(evt);
                    break;
                case "sim.tick_ended":
                    HandleTickEnded(evt.Payload);
                    PushTickEvent(evt);
                    break;
                case "sim.agent_action":
                    HandleAgentAction(evt.Payload);
                    PushTickEvent(evt);
                    break;
                case "sim.agent_state":
                    HandleAgentState(evt.Payload);
                    PushTickEvent(evt);
                    break;
                case "sim.interaction":
                    HandleInteraction(evt.Payload);
                    PushTickEvent(evt);
                    break;
                case "sim.world_event":
                    HandleWorldEvent(evt.Payload);
                    PushTickEvent(evt);
                    break;
                default:
                    break;
            }
        }

        private void HandleStreamStatus(string status, string detail)
        {
            SetStatusMessage(string.IsNullOrEmpty(detail) ? $"SSE: {status}" : $"SSE: {status} — {detail}");
        }

        private void HandleTickStarted(JObject payload)
        {
            int startedTick = PayloadInt(payload, "tick");
            int startedHour = PayloadInt(payload, "hour");
            ticking = true;
            if (startedTick > 0)
            {
                Tick = startedTick;
            }

            if (startedHour > 0)
            {
                Hour = startedHour;
            }

            SetStatusMessage($"Tick {(startedTick > 0 ? startedTick : Tick)} started…");
        }

        private void HandleTickEnded(JObject payload)
        {
            int endedTick = PayloadInt(payload, "tick");
            int endedHour = PayloadInt(payload, "hour");
            ticking = false;
            Tick = Mathf.Max(Tick, endedTick);
            Hour = endedHour;

            if (IsReplayActive)
            {
                return;
            }

            seekGeneration++;
            int generation = seekGeneration;
            FireAndForget(FetchTickEndedAsync(endedTick, generation));
        }

        private async Task FetchTickEndedAsync(int endedTick, int generation)
        {
            bool ok = await FetchAndApplyTickAsync(endedTick, updatePlayhead: false);
            if (!ok || generation != seekGeneration || IsReplayActive)
            {
                // Superseded or entered replay meanwhile — result already dropped by ApplySnapshot guardrails.
            }
        }

        private void HandleAgentAction(JObject payload)
        {
            int eventTick = PayloadInt(payload, "tick");
            if (payload?["action"] is not JObject action)
            {
                return;
            }

            string agentId = PayloadString(action, "agent_id");
            string thought = PayloadString(action, "thought");
            string detail = PayloadString(action, "detail");
            string actionType = PayloadString(action, "action");

            string summary = thought.Trim();
            if (string.IsNullOrEmpty(summary))
            {
                summary = detail.Trim();
            }

            if (string.IsNullOrEmpty(summary))
            {
                summary = actionType;
            }

            string location = action["tool_args"] is JObject toolArgs
                ? PayloadString(toolArgs, "destination")
                : "";

            PushDecision(new SimDecision
            {
                Tick = eventTick,
                AgentId = agentId,
                Summary = summary,
                ActionType = actionType,
                Location = location,
            });
        }

        private void HandleAgentState(JObject payload)
        {
            if (payload?["state"] is not JObject stateObj)
            {
                return;
            }

            SimAgentState agent;
            try
            {
                agent = stateObj.ToObject<SimAgentState>(SimJson.Serializer);
            }
            catch (JsonException)
            {
                return;
            }

            if (agent == null || string.IsNullOrEmpty(agent.AgentId))
            {
                return;
            }

            agents[agent.AgentId] = agent;
            agentUnityPositions[agent.AgentId] = WireCoordinateTransform.ToUnity(agent.Position);

            // Backfill the freshest decision's resolved location from this tick's agent_state
            // (ST-02 oracle parity — Desktop foldSimulation does the same so the decisions feed
            // shows where the move/talk landed). Only when decisions[0] is this agent + tick.
            if (decisions.Count > 0
                && decisions[0].AgentId == agent.AgentId
                && decisions[0].Tick == PayloadInt(payload, "tick"))
            {
                decisions[0].Location = agent.Location;
                OnDecisionsChanged?.Invoke();
            }

            OnSnapshotApplied?.Invoke();
        }

        private void HandleInteraction(JObject payload)
        {
            if (!InteractionModel.TryParseFromPayload(payload, Time.realtimeSinceStartup, persistent: false, out ActiveInteraction ix)
                || ix == null)
            {
                return;
            }

            UpsertActiveInteraction(ix);
            PushDecision(new SimDecision
            {
                Tick = ix.Tick,
                AgentId = ix.InitiatorId,
                Summary = ix.Summary,
                ActionType = ix.Kind,
            });
        }

        private void HandleWorldEvent(JObject payload)
        {
            if (payload?["modifiers"] is JObject modObj)
            {
                try
                {
                    WorldModifiers parsed = modObj.ToObject<WorldModifiers>(SimJson.Serializer);
                    if (parsed != null)
                    {
                        modifiers = parsed;
                        OnSnapshotApplied?.Invoke();
                    }
                }
                catch (JsonException)
                {
                    // tolerate partial payloads
                }
            }
        }

        private void UpsertActiveInteraction(ActiveInteraction interaction)
        {
            if (interaction == null || string.IsNullOrEmpty(interaction.Id))
            {
                return;
            }

            activeInteractions[interaction.Id] = interaction;
            OnInteractionsChanged?.Invoke();
        }

        private void SyncOfflineInteractionsForTick(int tick)
        {
            if (!IsOffline)
            {
                return;
            }

            // Keep cues through hold+fade so overlays can dwell then fade (speed-scaled).
            // Worst case at 0.5×: hold≈5 + fade≈3 → look back ~8 ticks.
            int lookback = 8;
            activeInteractions.Clear();
            for (int t = Mathf.Max(1, tick - lookback); t <= tick; t++)
            {
                if (!offlineInteractionsByTick.TryGetValue(t, out List<ActiveInteraction> list))
                {
                    continue;
                }

                for (int i = 0; i < list.Count; i++)
                {
                    ActiveInteraction ix = list[i];
                    if (ix == null || string.IsNullOrEmpty(ix.Id))
                    {
                        continue;
                    }

                    float alpha = InteractionModel.OverlayAlpha(ix, tick, offline: true, PlaybackSpeed);
                    if (alpha > 0.04f)
                    {
                        activeInteractions[ix.Id] = ix;
                    }
                }
            }

            OnInteractionsChanged?.Invoke();
        }

        private void PruneExpiredInteractions()
        {
            if (IsOffline || activeInteractions.Count == 0)
            {
                return;
            }

            float now = Time.realtimeSinceStartup;
            var expired = new List<string>();
            foreach (KeyValuePair<string, ActiveInteraction> pair in activeInteractions)
            {
                if (pair.Value != null && pair.Value.ExpiresAtRealtime < now)
                {
                    expired.Add(pair.Key);
                }
            }

            if (expired.Count == 0)
            {
                return;
            }

            for (int i = 0; i < expired.Count; i++)
            {
                activeInteractions.Remove(expired[i]);
            }

            OnInteractionsChanged?.Invoke();
        }

        private void PushDecision(SimDecision decision)
        {
            decisions.Insert(0, decision);
            if (decisions.Count > MaxDecisions)
            {
                decisions.RemoveRange(MaxDecisions, decisions.Count - MaxDecisions);
            }

            OnDecisionsChanged?.Invoke();
        }

        private void PushTickEvent(SimSseEvent evt)
        {
            tickEvents.Insert(0, new SimTickEvent
            {
                Tick = PayloadInt(evt.Payload, "tick"),
                Type = evt.Type,
                AgentId = ExtractEventAgentId(evt),
                Summary = ExtractEventSummary(evt),
                Detail = ExtractEventDetail(evt),
                Timestamp = evt.Timestamp,
            });

            if (tickEvents.Count > MaxTickEvents)
            {
                tickEvents.RemoveRange(MaxTickEvents, tickEvents.Count - MaxTickEvents);
            }

            OnEventsChanged?.Invoke();
        }

        /// <summary>Test hook: dispatch one live SSE envelope through the same path as the stream.</summary>
        internal void IngestSseEvent(SimSseEvent evt) => HandleSseEvent(evt);

        /// <summary>
        /// Prefer payload summary / title / thought over the raw event type name so the
        /// Events tab stays readable on Live SSE (Offline already writes Summary by hand).
        /// </summary>
        internal static string ExtractEventSummary(SimSseEvent evt)
        {
            if (evt == null)
            {
                return "";
            }

            JObject payload = evt.Payload;
            if (payload == null)
            {
                return string.IsNullOrEmpty(evt.Type) ? "" : evt.Type;
            }

            switch (evt.Type)
            {
                case "sim.interaction":
                {
                    if (payload["interaction"] is JObject ix)
                    {
                        string summary = PayloadString(ix, "summary");
                        if (!string.IsNullOrEmpty(summary))
                        {
                            return summary;
                        }

                        string kind = PayloadString(ix, "kind");
                        if (!string.IsNullOrEmpty(kind))
                        {
                            return kind;
                        }
                    }

                    break;
                }
                case "sim.world_event":
                {
                    if (payload["event"] is JObject worldEvt)
                    {
                        string title = PayloadString(worldEvt, "title");
                        if (!string.IsNullOrEmpty(title))
                        {
                            return title;
                        }

                        string description = PayloadString(worldEvt, "description");
                        if (!string.IsNullOrEmpty(description))
                        {
                            return description;
                        }

                        string kind = PayloadString(worldEvt, "kind");
                        if (string.IsNullOrEmpty(kind))
                        {
                            kind = PayloadString(worldEvt, "event_type");
                        }

                        if (!string.IsNullOrEmpty(kind))
                        {
                            return kind;
                        }
                    }

                    break;
                }
                case "sim.agent_action":
                {
                    if (payload["action"] is JObject action)
                    {
                        string thought = PayloadString(action, "thought");
                        if (!string.IsNullOrEmpty(thought))
                        {
                            return thought;
                        }

                        string detail = PayloadString(action, "detail");
                        if (!string.IsNullOrEmpty(detail))
                        {
                            return detail;
                        }

                        string actionType = PayloadString(action, "action");
                        if (!string.IsNullOrEmpty(actionType))
                        {
                            return actionType;
                        }
                    }

                    break;
                }
                case "sim.tick_started":
                case "sim.tick_ended":
                {
                    int tick = PayloadInt(payload, "tick");
                    if (tick > 0)
                    {
                        return evt.Type == "sim.tick_started"
                            ? $"tick {tick} started"
                            : $"tick {tick} ended";
                    }

                    break;
                }
            }

            string top = PayloadString(payload, "summary");
            if (!string.IsNullOrEmpty(top))
            {
                return top;
            }

            return string.IsNullOrEmpty(evt.Type) ? "" : evt.Type;
        }

        /// <summary>Multi-line transcript (or world-event description) for the Events tab body.</summary>
        internal static string ExtractEventDetail(SimSseEvent evt)
        {
            if (evt?.Payload == null)
            {
                return "";
            }

            JObject payload = evt.Payload;
            switch (evt.Type)
            {
                case "sim.interaction":
                {
                    if (payload["interaction"] is not JObject ixObj)
                    {
                        return "";
                    }

                    InteractionResult result;
                    try
                    {
                        result = ixObj.ToObject<InteractionResult>(SimJson.Serializer);
                    }
                    catch (JsonException)
                    {
                        return "";
                    }

                    return InteractionModel.FormatTranscript(result?.Transcript);
                }
                case "sim.world_event":
                {
                    if (payload["event"] is not JObject worldEvt)
                    {
                        return "";
                    }

                    string title = PayloadString(worldEvt, "title");
                    string description = PayloadString(worldEvt, "description");
                    if (string.IsNullOrEmpty(description) || description == title)
                    {
                        return "";
                    }

                    return description;
                }
                default:
                    return "";
            }
        }

        internal static string ExtractEventAgentId(SimSseEvent evt)
        {
            JObject payload = evt?.Payload;
            if (payload == null)
            {
                return "";
            }

            if (payload["interaction"] is JObject interaction)
            {
                string initiator = PayloadString(interaction, "initiator_id");
                if (!string.IsNullOrEmpty(initiator))
                {
                    return initiator;
                }
            }

            if (payload["action"] is JObject action)
            {
                string fromAction = PayloadString(action, "agent_id");
                if (!string.IsNullOrEmpty(fromAction))
                {
                    return fromAction;
                }
            }

            if (payload["state"] is JObject state)
            {
                string fromState = PayloadString(state, "agent_id");
                if (!string.IsNullOrEmpty(fromState))
                {
                    return fromState;
                }
            }

            return PayloadString(payload, "agent_id");
        }

        private static int PayloadInt(JObject payload, string key, int fallback = 0)
        {
            JToken token = payload?[key];
            if (token == null || token.Type == JTokenType.Null)
            {
                return fallback;
            }

            try
            {
                return token.Value<int>();
            }
            catch (Exception)
            {
                return fallback;
            }
        }

        private static string PayloadString(JObject payload, string key, string fallback = "")
        {
            JToken token = payload?[key];
            if (token == null || token.Type == JTokenType.Null)
            {
                return fallback;
            }

            try
            {
                return token.Value<string>() ?? fallback;
            }
            catch (Exception)
            {
                return fallback;
            }
        }

        private static async void FireAndForget(Task task)
        {
            try
            {
                await task;
            }
            catch (Exception e)
            {
                Debug.LogException(e);
            }
        }

        private static string TrimTrailingSlashes(string value)
        {
            string result = value;
            while (result.EndsWith("/", StringComparison.Ordinal))
            {
                result = result.Substring(0, result.Length - 1);
            }

            return result;
        }
    }
}
