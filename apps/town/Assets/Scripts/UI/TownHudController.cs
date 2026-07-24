using System;
using System.Collections.Generic;
using AgentTown.Simulation;
using AgentTown.Town;
using UnityEngine;
using UnityEngine.UIElements;

namespace AgentTown.UI
{
    /// <summary>
    /// UI Toolkit observer panel controller (§7 UiLayer). Binds <c>TownHud.uxml</c> to
    /// <see cref="SimulationSession"/>: run management, offline demo, tick / playback slider,
    /// metrics, modifier chips, God Mode inject, residents, decisions, events, tracking.
    /// </summary>
    [RequireComponent(typeof(UIDocument))]
    [DisallowMultipleComponent]
    public sealed class TownHudController : MonoBehaviour
    {
        [Tooltip("Optional: applied at runtime if the UXML does not already link TownHud.uss.")]
        [SerializeField] private StyleSheet styleSheet;

        private static readonly (string name, float value)[] SpeedButtons =
        {
            ("speed-05", 0.5f), ("speed-1", 1f), ("speed-2", 2f), ("speed-4", 4f),
        };

        private static readonly (string buttonName, string eventType)[] GodPresets =
        {
            ("inject-price", "price_surge"),
            ("inject-storm", "storm"),
            ("inject-festival", "festival"),
            ("inject-announce", "announcement"),
        };

        private UIDocument document;
        private SimulationSession session;
        private bool bound;
        private bool seekSliderDragging;

        private Label statusLabel;
        private Label modeBadge;
        private Label tickLabel;
        private Label fpsLabel;
        private Label streamLabel;
        private Label clockLabel;
        private readonly FpsSampler fpsSampler = new FpsSampler();
        private Button demoButton;
        private Button showButton;
        private DropdownField packDropdown;
        private string selectedPackId = DemoPackIds.PriceSurge;
        private bool packDropdownWiring;
        private Button createRunButton;
        private Button resumeRunButton;
        private TextField runIdField;
        private ScrollView runHistoryList;
        private Button advanceButton;
        private Button pauseButton;
        private Button resumeTickButton;
        private Button prevButton;
        private Button playButton;
        private Button nextButton;
        private Button nextStoryButton;
        private Button liveButton;
        private Button birdseyeButton;
        private SliderInt seekSlider;
        private Label metricMood;
        private Label metricTrade;
        private Label metricRelation;
        private Label metricPop;
        private VisualElement modifierChips;
        private Label godHint;
        private VisualElement liveRunBlock;
        private VisualElement offlineWatchBlock;
        private VisualElement godModeBlock;
        private Label offlinePackTitle;
        private Label offlinePackSynopsis;
        private Label offlineNowLabel;
        private bool offlineEventsTabApplied;
        private readonly List<Button> godButtons = new();
        private ScrollView residentsList;
        private VisualElement residentDetail;
        private ScrollView decisionsList;
        private ScrollView eventsList;
        private Button tabResidents;
        private Button tabDecisions;
        private Button tabEvents;
        private VisualElement paneResidents;
        private VisualElement paneDecisions;
        private VisualElement paneEvents;
        private string activeInspectTab = "residents";

        private Label storyBeatLabel;
        private Label timelineStoryLabel;
        private VisualElement packIntroCard;
        private Label packIntroTitle;
        private Label packIntroSynopsis;
        private VisualElement packIntroCast;
        private Button packIntroDismiss;
        private float packIntroHideAt = -1f;
        private List<StoryBeatProgress.PulseMark> cachedPulses = new();
        private string cachedPulsePackId = "";

        /// <summary>Point the controller at a session (defaults to the singleton).</summary>
        public void Bind(SimulationSession target)
        {
            Unsubscribe();
            session = target;
            Subscribe();
            if (bound)
            {
                RefreshAll();
            }
        }

        private void OnEnable()
        {
            document = GetComponent<UIDocument>();
            session ??= SimulationSession.Instance;
            Subscribe();
            TryBind();
        }

        private void OnDisable() => Unsubscribe();

        private void Update()
        {
            if (!bound)
            {
                TryBind();
            }

            if (!bound || fpsLabel == null)
            {
                return;
            }

            if (packIntroHideAt > 0f && Time.unscaledTime >= packIntroHideAt)
            {
                HidePackIntro();
            }

            if (fpsSampler.AddFrame(Time.unscaledDeltaTime))
            {
                RefreshFpsLabel();
            }
        }

        private void Subscribe()
        {
            if (session == null)
            {
                return;
            }

            session.OnStatusChanged += HandleStatusChanged;
            session.OnSnapshotApplied += HandleSnapshotApplied;
            session.OnPlaybackChanged += RefreshPlayback;
            session.OnSelectionChanged += RefreshResidents;
            session.OnDecisionsChanged += RefreshDecisions;
            session.OnEventsChanged += RefreshEvents;
            session.OnInteractionsChanged += HandleInteractionsChanged;
        }

        private void Unsubscribe()
        {
            if (session == null)
            {
                return;
            }

            session.OnStatusChanged -= HandleStatusChanged;
            session.OnSnapshotApplied -= HandleSnapshotApplied;
            session.OnPlaybackChanged -= RefreshPlayback;
            session.OnSelectionChanged -= RefreshResidents;
            session.OnDecisionsChanged -= RefreshDecisions;
            session.OnEventsChanged -= RefreshEvents;
            session.OnInteractionsChanged -= HandleInteractionsChanged;
        }

        private void TryBind()
        {
            if (document == null)
            {
                return;
            }

            VisualElement root = document.rootVisualElement;
            createRunButton = root?.Q<Button>("create-run-button");
            if (createRunButton == null)
            {
                return; // visual tree not ready yet — retry next frame
            }

            if (styleSheet != null && !root.styleSheets.Contains(styleSheet))
            {
                root.styleSheets.Add(styleSheet);
            }

            // WebGL panels have no OS font fallback — pin the bundled CJK subset on the
            // panel root so every label (HUD, nameplates, show faces) inherits it.
            Font uiFont = TownFonts.UiFont;
            if (uiFont != null)
            {
                root.style.unityFontDefinition =
                    new StyleFontDefinition(FontDefinition.FromFont(uiFont));
            }

            statusLabel = root.Q<Label>("status-label");
            modeBadge = root.Q<Label>("mode-badge");
            tickLabel = root.Q<Label>("tick-label");
            fpsLabel = root.Q<Label>("fps-label");
            streamLabel = root.Q<Label>("stream-label");
            clockLabel = root.Q<Label>("clock-label");
            demoButton = root.Q<Button>("demo-button");
            showButton = root.Q<Button>("show-button");
            packDropdown = root.Q<DropdownField>("pack-dropdown");
            resumeRunButton = root.Q<Button>("resume-run-button");
            runIdField = root.Q<TextField>("run-id-field");
            runHistoryList = root.Q<ScrollView>("run-history-list");
            advanceButton = root.Q<Button>("advance-button");
            pauseButton = root.Q<Button>("pause-button");
            resumeTickButton = root.Q<Button>("resume-tick-button");
            prevButton = root.Q<Button>("prev-button");
            playButton = root.Q<Button>("play-button");
            nextButton = root.Q<Button>("next-button");
            nextStoryButton = root.Q<Button>("next-story-button");
            liveButton = root.Q<Button>("live-button");
            birdseyeButton = root.Q<Button>("birdseye-button");
            seekSlider = root.Q<SliderInt>("seek-slider");
            metricMood = root.Q<Label>("metric-mood");
            metricTrade = root.Q<Label>("metric-trade");
            metricRelation = root.Q<Label>("metric-relation");
            metricPop = root.Q<Label>("metric-pop");
            modifierChips = root.Q<VisualElement>("modifier-chips");
            godHint = root.Q<Label>("god-hint");
            liveRunBlock = root.Q<VisualElement>("live-run-block");
            offlineWatchBlock = root.Q<VisualElement>("offline-watch-block");
            godModeBlock = root.Q<VisualElement>("god-mode-block");
            offlinePackTitle = root.Q<Label>("offline-pack-title");
            offlinePackSynopsis = root.Q<Label>("offline-pack-synopsis");
            offlineNowLabel = root.Q<Label>("offline-now-label");
            residentsList = root.Q<ScrollView>("residents-list");
            residentDetail = root.Q<VisualElement>("resident-detail");
            decisionsList = root.Q<ScrollView>("decisions-list");
            eventsList = root.Q<ScrollView>("events-list");
            tabResidents = root.Q<Button>("tab-residents");
            tabDecisions = root.Q<Button>("tab-decisions");
            tabEvents = root.Q<Button>("tab-events");
            paneResidents = root.Q<VisualElement>("tab-pane-residents");
            paneDecisions = root.Q<VisualElement>("tab-pane-decisions");
            paneEvents = root.Q<VisualElement>("tab-pane-events");
            storyBeatLabel = root.Q<Label>("story-beat-label");
            timelineStoryLabel = root.Q<Label>("timeline-story-label");
            packIntroCard = root.Q<VisualElement>("pack-intro-card");
            packIntroTitle = root.Q<Label>("pack-intro-title");
            packIntroSynopsis = root.Q<Label>("pack-intro-synopsis");
            packIntroCast = root.Q<VisualElement>("pack-intro-cast");
            packIntroDismiss = root.Q<Button>("pack-intro-dismiss");

            WireButtons();
            ShowInspectTab(activeInspectTab);
            bound = true;
            RefreshAll();
        }

        private void WireButtons()
        {
            if (demoButton != null)
            {
                demoButton.clicked += StartOfflineDemo;
            }

            if (showButton != null)
            {
                showButton.clicked += StartShowMode;
            }

            WirePackDropdown();

            createRunButton.clicked += () => _ = session.CreateRunAsync();
            if (resumeRunButton != null)
            {
                resumeRunButton.clicked += () => _ = session.AttachToRunAsync(runIdField?.value?.Trim() ?? "");
            }

            if (advanceButton != null) advanceButton.clicked += () => _ = session.AdvanceTickAsync();
            if (pauseButton != null) pauseButton.clicked += () => _ = session.PauseRunAsync();
            if (resumeTickButton != null) resumeTickButton.clicked += () => _ = session.ResumeRunAsync();

            if (prevButton != null) prevButton.clicked += () => session.StepPlaybackTick(-1);
            if (nextButton != null) nextButton.clicked += () => session.StepPlaybackTick(1);
            if (nextStoryButton != null) nextStoryButton.clicked += () => session.SeekNextStoryTick();
            if (liveButton != null) liveButton.clicked += () => session.GoLive();
            if (playButton != null) playButton.clicked += TogglePlay;
            if (birdseyeButton != null) birdseyeButton.clicked += ReturnToBirdseye;

            if (tabResidents != null) tabResidents.clicked += () => ShowInspectTab("residents");
            if (tabDecisions != null) tabDecisions.clicked += () => ShowInspectTab("decisions");
            if (tabEvents != null) tabEvents.clicked += () => ShowInspectTab("events");

            if (seekSlider != null)
            {
                seekSlider.RegisterCallback<PointerDownEvent>(_ => seekSliderDragging = true);
                seekSlider.RegisterCallback<PointerUpEvent>(_ =>
                {
                    seekSliderDragging = false;
                    SeekFromSlider();
                    RefreshTimelineStory();
                });
                seekSlider.RegisterValueChangedCallback(evt =>
                {
                    if (seekSliderDragging)
                    {
                        SeekFromSlider(evt.newValue);
                        RefreshTimelineStory(evt.newValue);
                        if (seekSlider != null)
                        {
                            seekSlider.tooltip = StoryBeatProgress.TooltipForTick(
                                evt.newValue, EnsurePulses());
                        }
                    }
                });
            }

            if (packIntroDismiss != null)
            {
                packIntroDismiss.clicked += HidePackIntro;
            }

            godButtons.Clear();
            foreach ((string buttonName, string eventType) in GodPresets)
            {
                Button button = document.rootVisualElement.Q<Button>(buttonName);
                if (button == null)
                {
                    continue;
                }

                string captured = eventType;
                button.clicked += () => _ = session.InjectEventAsync(captured);
                godButtons.Add(button);
            }

            foreach ((string speedName, float value) in SpeedButtons)
            {
                Button button = document.rootVisualElement.Q<Button>(speedName);
                if (button != null)
                {
                    button.clicked += () => session.SetPlaybackSpeed(value);
                }
            }
        }

        private void WirePackDropdown()
        {
            if (packDropdown == null || packDropdownWiring)
            {
                return;
            }

            packDropdownWiring = true;
            var choices = new List<string>();
            foreach (string id in DemoPackIds.All)
            {
                choices.Add(DemoPackIds.DisplayName(id));
            }

            packDropdown.choices = choices;
            packDropdown.index = IndexForPack(selectedPackId);
            packDropdown.RegisterValueChangedCallback(evt =>
            {
                int idx = packDropdown.index;
                if (idx < 0 || idx >= DemoPackIds.All.Length)
                {
                    return;
                }

                string next = DemoPackIds.All[idx];
                if (next == selectedPackId && session != null && session.IsOffline
                    && session.OfflinePackId == next)
                {
                    return;
                }

                selectedPackId = next;
                StartOfflineDemo();
            });
        }

        private static int IndexForPack(string packId)
        {
            string resolved = DemoPackIds.Normalize(packId);
            for (int i = 0; i < DemoPackIds.All.Length; i++)
            {
                if (DemoPackIds.All[i] == resolved)
                {
                    return i;
                }
            }

            return 0;
        }

        private void SeekFromSlider(int? value = null)
        {
            if (session == null || seekSlider == null)
            {
                return;
            }

            int tick = value ?? seekSlider.value;
            session.SetPlaying(false);
            session.SeekTick(tick);
        }

        private void StartOfflineDemo()
        {
            string packId = selectedPackId;
            if (packDropdown != null && packDropdown.index >= 0
                && packDropdown.index < DemoPackIds.All.Length)
            {
                packId = DemoPackIds.All[packDropdown.index];
                selectedPackId = packId;
            }

            TownBootstrap bootstrap = FindFirstObjectByType<TownBootstrap>();
            if (bootstrap != null)
            {
                bootstrap.StartOfflineDemo(packId);
                return;
            }

            // Fallback when HUD is present without bootstrap (tests / partial scenes).
            DemoStoryPackCatalog.EnsureLoadedForBuild();
            Dictionary<string, WireVec3> regions = RegionPositions.LoadFromFile();
            OfflineDemoPack pack = OfflineDemoBuilder.Build(
                TownPersonas.All, regions, packId: packId);
            session.EnterOfflineDemo(pack);
            if (pack.Interactions != null && pack.Interactions.Count > 0 && pack.Interactions[0].Tick > 1)
            {
                session.SeekTick(pack.Interactions[0].Tick);
            }

            session.SetPlaying(true);
            ShowPackIntro(packId);
        }

        private void StartShowMode()
        {
            TownBootstrap bootstrap = FindFirstObjectByType<TownBootstrap>();
            if (bootstrap != null)
            {
                bootstrap.StartShowEpisode3();
                return;
            }

            AgentTown.Show.ShowModeController show = FindFirstObjectByType<AgentTown.Show.ShowModeController>();
            if (show != null)
            {
                _ = show.EnterEpisode3Async();
            }
        }

        /// <summary>
        /// Programme mode hides observatory chrome (rails / metrics / timeline / god).
        /// Exit restores visibility.
        /// </summary>
        public void SetObservatoryChromeVisible(bool visible)
        {
            if (!bound)
            {
                TryBind();
            }

            VisualElement root = document != null ? document.rootVisualElement : null;
            if (root == null)
            {
                return;
            }

            SetDisplay(root.Q("top-bar"), visible);
            SetDisplay(root.Q("bottom-bar"), visible);
            SetDisplay(root.Q("control-panel"), visible);
            SetDisplay(root.Q("residents-panel"), visible);
            if (!visible)
            {
                HidePackIntro();
            }
        }

        /// <summary>Called by <see cref="TownBootstrap"/> after Offline bake so the intro card appears.</summary>
        public void ShowPackIntro(string packId)
        {
            if (!bound)
            {
                TryBind();
            }

            DemoStoryPackCatalog.EnsureLoadedForBuild();
            string id = DemoPackIds.Normalize(packId);
            if (!DemoStoryPackCatalog.TryGet(id, out DemoStoryPackDef def))
            {
                HidePackIntro();
                return;
            }

            if (packIntroCard == null)
            {
                return;
            }

            if (packIntroTitle != null)
            {
                packIntroTitle.text = string.IsNullOrEmpty(def.DisplayName)
                    ? DemoPackIds.DisplayName(id)
                    : def.DisplayName;
            }

            if (packIntroSynopsis != null)
            {
                packIntroSynopsis.text = string.IsNullOrEmpty(def.Synopsis)
                    ? "离线演示剧本，无需后端。"
                    : def.Synopsis;
            }

            if (packIntroCast != null)
            {
                packIntroCast.Clear();
                if (def.Cast != null)
                {
                    foreach (DemoStoryCastDef member in def.Cast)
                    {
                        if (member == null)
                        {
                            continue;
                        }

                        string name = string.IsNullOrEmpty(member.Name) ? member.AgentId : member.Name;
                        string blurb = member.Blurb ?? "";
                        var row = new Label(string.IsNullOrEmpty(blurb) ? name : $"{name} — {blurb}");
                        row.AddToClassList("pack-intro-cast-row");
                        packIntroCast.Add(row);
                    }
                }
            }

            packIntroCard.RemoveFromClassList("hidden");
            packIntroHideAt = Time.unscaledTime + 8f;
            InvalidatePulseCache();
            RefreshStoryBeat();
            RefreshTimelineStory();
        }

        private void HidePackIntro()
        {
            packIntroHideAt = -1f;
            packIntroCard?.AddToClassList("hidden");
        }

        private void InvalidatePulseCache()
        {
            cachedPulsePackId = "";
            cachedPulses = new List<StoryBeatProgress.PulseMark>();
        }

        private List<StoryBeatProgress.PulseMark> EnsurePulses()
        {
            if (session == null || !session.IsOffline)
            {
                cachedPulses = new List<StoryBeatProgress.PulseMark>();
                cachedPulsePackId = "";
                return cachedPulses;
            }

            string packId = session.OfflinePackId ?? "";
            if (packId == cachedPulsePackId && cachedPulses != null && cachedPulses.Count > 0)
            {
                return cachedPulses;
            }

            cachedPulsePackId = packId;
            cachedPulses = StoryBeatProgress.FromInteractions(session.OfflineStoryInteractions);
            return cachedPulses;
        }

        private void ReturnToBirdseye()
        {
            session?.SetTrackedAgent(null);
            session?.SetSelectedAgent(null);
            TownCamera cam = FindFirstObjectByType<TownCamera>();
            cam?.Frame();
        }

        private void ShowInspectTab(string tab)
        {
            activeInspectTab = tab ?? "residents";
            SetTabActive(tabResidents, activeInspectTab == "residents");
            SetTabActive(tabDecisions, activeInspectTab == "decisions");
            SetTabActive(tabEvents, activeInspectTab == "events");
            SetPaneVisible(paneResidents, activeInspectTab == "residents");
            SetPaneVisible(paneDecisions, activeInspectTab == "decisions");
            SetPaneVisible(paneEvents, activeInspectTab == "events");
        }

        private static void SetTabActive(Button tab, bool active)
        {
            if (tab == null)
            {
                return;
            }

            if (active) tab.AddToClassList("active");
            else tab.RemoveFromClassList("active");
        }

        private static void SetPaneVisible(VisualElement pane, bool visible)
        {
            if (pane == null)
            {
                return;
            }

            if (visible) pane.RemoveFromClassList("hidden");
            else pane.AddToClassList("hidden");
        }

        private void TogglePlay()
        {
            if (session.Playing)
            {
                session.SetPlaying(false);
                return;
            }

            // Entering playback from live starts a replay at the first tick (mirrors Desktop / UE).
            if (session.IsLive && session.Tick >= 1)
            {
                session.SeekTick(1);
            }

            session.SetPlaying(true);
        }

        // ---- refresh ----

        private void HandleStatusChanged(string _)
        {
            RefreshStatus();
            RefreshRunHistory();
        }

        private void HandleSnapshotApplied()
        {
            RefreshStatus();
            RefreshResidents();
            RefreshRunHistory();
            RefreshPlayback();
            RefreshMetrics();
            RefreshModifiers();
            RefreshDecisions();
            RefreshEvents();
            RefreshOfflineWatch();
        }

        private void HandleInteractionsChanged()
        {
            RefreshEvents();
            RefreshOfflineWatch();
        }

        private void RefreshAll()
        {
            RefreshStatus();
            RefreshPlayback();
            RefreshResidents();
            RefreshRunHistory();
            RefreshDecisions();
            RefreshEvents();
            RefreshMetrics();
            RefreshModifiers();
            RefreshFpsLabel();
            RefreshOfflineWatch();
            ApplyModeChrome();
        }

        private void RefreshFpsLabel()
        {
            if (fpsLabel == null)
            {
                return;
            }

            float fps = fpsSampler.LastFps;
            fpsLabel.text = FpsSampler.FormatLabel(fps);
            ApplyFpsBandClass(fpsSampler.LastBand);
        }

        private void ApplyFpsBandClass(FpsSampler.Band band)
        {
            fpsLabel.RemoveFromClassList("fps-ok");
            fpsLabel.RemoveFromClassList("fps-warn");
            fpsLabel.RemoveFromClassList("fps-critical");
            fpsLabel.RemoveFromClassList("fps-unknown");
            fpsLabel.AddToClassList(FpsSampler.BandClass(band));
        }

        private void RefreshStatus()
        {
            if (!bound || session == null)
            {
                return;
            }

            if (statusLabel != null)
            {
                statusLabel.text = session.StatusMessage;
            }

            RefreshModeBadge();

            if (session.IsOffline && !string.IsNullOrEmpty(session.OfflinePackId))
            {
                selectedPackId = DemoPackIds.Normalize(session.OfflinePackId);
                if (packDropdown != null && packDropdown.index != IndexForPack(selectedPackId))
                {
                    packDropdown.SetValueWithoutNotify(DemoPackIds.DisplayName(selectedPackId));
                }
            }

            bool offline = session.IsOffline;
            bool hasRun = !string.IsNullOrEmpty(session.RunId);
            bool busy = session.Ticking;

            demoButton?.SetEnabled(!busy);
            packDropdown?.SetEnabled(!busy);
            createRunButton?.SetEnabled(!busy && !offline);
            resumeRunButton?.SetEnabled(!busy && !offline);
            advanceButton?.SetEnabled(hasRun && !busy && !offline);
            pauseButton?.SetEnabled(hasRun && !offline);
            resumeTickButton?.SetEnabled(hasRun && !offline);
            prevButton?.SetEnabled(hasRun);
            playButton?.SetEnabled(hasRun);
            nextButton?.SetEnabled(hasRun);
            liveButton?.SetEnabled(hasRun);
            birdseyeButton?.SetEnabled(!string.IsNullOrEmpty(session.TrackedAgentId));
            seekSlider?.SetEnabled(hasRun);

            bool godOk = hasRun && !offline && !busy;
            foreach (Button god in godButtons)
            {
                god?.SetEnabled(godOk);
            }

            if (godHint != null)
            {
                godHint.text = offline
                    ? "离线演示不可注入 — 请新建/恢复 Run"
                    : !hasRun
                        ? "请先创建或恢复一个模拟 Run"
                        : "向世界注入事件，影响下一 tick";
            }

            ApplyModeChrome();
            RefreshOfflineWatch();

            if (offline && !offlineEventsTabApplied)
            {
                offlineEventsTabApplied = true;
                ShowInspectTab("events");
            }
            else if (!offline)
            {
                offlineEventsTabApplied = false;
            }
        }

        /// <summary>
        /// Offline hides Live run-id / God inject chrome and shows a watch brief instead.
        /// Live layout is unchanged when not offline.
        /// </summary>
        private void ApplyModeChrome()
        {
            if (!bound || session == null)
            {
                return;
            }

            bool offline = session.IsOffline;
            SetDisplay(liveRunBlock, !offline);
            SetDisplay(godModeBlock, !offline);
            SetDisplay(offlineWatchBlock, offline);
            if (createRunButton != null)
            {
                createRunButton.style.display = offline ? DisplayStyle.None : DisplayStyle.Flex;
            }
        }

        private static void SetDisplay(VisualElement element, bool visible)
        {
            if (element == null)
            {
                return;
            }

            if (visible)
            {
                element.RemoveFromClassList("hidden");
                element.style.display = DisplayStyle.Flex;
            }
            else
            {
                element.AddToClassList("hidden");
                element.style.display = DisplayStyle.None;
            }
        }

        /// <summary>
        /// Left-rail Offline brief from catalog synopsis + current beat / active interaction
        /// (existing Offline data only — no invented copy).
        /// </summary>
        private void RefreshOfflineWatch()
        {
            if (!bound || session == null || !session.IsOffline)
            {
                return;
            }

            string packId = DemoPackIds.Normalize(session.OfflinePackId);
            DemoStoryPackCatalog.EnsureLoadedForBuild();
            if (DemoStoryPackCatalog.TryGet(packId, out DemoStoryPackDef def))
            {
                if (offlinePackTitle != null)
                {
                    offlinePackTitle.text = string.IsNullOrEmpty(def.DisplayName)
                        ? DemoPackIds.DisplayName(packId)
                        : def.DisplayName;
                }

                if (offlinePackSynopsis != null)
                {
                    offlinePackSynopsis.text = string.IsNullOrEmpty(def.Synopsis)
                        ? "离线演示 · 无需后端"
                        : def.Synopsis;
                }
            }
            else if (offlinePackTitle != null)
            {
                offlinePackTitle.text = DemoPackIds.DisplayName(packId);
            }

            if (offlineNowLabel == null)
            {
                return;
            }

            string now = FormatCurrentWatchLine();
            offlineNowLabel.text = string.IsNullOrEmpty(now) ? "日常过渡中…" : now;
        }

        private string FormatCurrentWatchLine()
        {
            if (session == null)
            {
                return "";
            }

            foreach (KeyValuePair<string, ActiveInteraction> pair in session.ActiveInteractions)
            {
                ActiveInteraction ix = pair.Value;
                if (ix == null || string.IsNullOrEmpty(ix.Summary))
                {
                    continue;
                }

                string kind = string.IsNullOrEmpty(ix.Kind) ? "互动" : ix.Kind;
                return $"当前 · {kind}：{ix.Summary}";
            }

            List<StoryBeatProgress.PulseMark> pulses = EnsurePulses();
            StoryBeatProgress.BarState bar = StoryBeatProgress.Resolve(
                DemoPackIds.DisplayName(session.OfflinePackId),
                session.DisplayTick,
                pulses);
            if (!string.IsNullOrEmpty(bar.Text))
            {
                return bar.Text;
            }

            return $"Tick {session.DisplayTick} / {session.Tick}";
        }

        private void RefreshModeBadge()
        {
            if (modeBadge == null || session == null)
            {
                return;
            }

            modeBadge.RemoveFromClassList("mode-badge--offline");
            modeBadge.RemoveFromClassList("mode-badge--live");
            modeBadge.RemoveFromClassList("mode-badge--replay");

            if (session.IsOffline)
            {
                modeBadge.text = $"离线演示 · {DemoPackIds.DisplayName(session.OfflinePackId)}";
                modeBadge.AddToClassList("mode-badge--offline");
            }
            else if (session.IsLive)
            {
                modeBadge.text = "Live";
                modeBadge.AddToClassList("mode-badge--live");
            }
            else
            {
                modeBadge.text = "Replay";
                modeBadge.AddToClassList("mode-badge--replay");
            }
        }

        private void RefreshRunHistory()
        {
            if (!bound || runHistoryList == null)
            {
                return;
            }

            runHistoryList.Clear();
            List<SavedRunEntry> runs = LocalRunHistory.List();
            if (runs.Count == 0)
            {
                var empty = new Label("暂无历史 — 新建或恢复后会出现在此");
                empty.AddToClassList("run-history-empty");
                runHistoryList.Add(empty);
                return;
            }

            bool busy = session != null && session.Ticking;
            foreach (SavedRunEntry entry in runs)
            {
                runHistoryList.Add(BuildHistoryRow(entry, busy));
            }
        }

        private VisualElement BuildHistoryRow(SavedRunEntry entry, bool busy)
        {
            var row = new VisualElement { name = $"history-{entry.Id}" };
            row.AddToClassList("run-history-row");
            row.SetEnabled(!busy);

            string shortId = entry.Id.Length > 12 ? entry.Id.Substring(0, 12) + "…" : entry.Id;
            var idLabel = new Label(shortId);
            idLabel.AddToClassList("run-history-id");
            idLabel.tooltip = entry.Id;

            string tickPart = entry.LastTick.HasValue ? $"tick {entry.LastTick.Value}" : "tick —";
            string scenario = string.IsNullOrEmpty(entry.Scenario) ? "town" : entry.Scenario;
            var meta = new Label($"{scenario} · {tickPart}");
            meta.AddToClassList("run-history-meta");

            row.Add(idLabel);
            row.Add(meta);
            row.RegisterCallback<ClickEvent>(_ => ResumeFromHistory(entry.Id));
            return row;
        }

        private void ResumeFromHistory(string runId)
        {
            if (session == null || string.IsNullOrEmpty(runId) || session.Ticking)
            {
                return;
            }

            if (runIdField != null)
            {
                runIdField.value = runId;
            }

            _ = session.AttachToRunAsync(runId);
        }

        private void RefreshPlayback()
        {
            if (!bound || session == null)
            {
                return;
            }

            if (tickLabel != null)
            {
                string playing = session.Playing ? " ▶" : "";
                if (session.IsOffline)
                {
                    tickLabel.text =
                        $"Tick {session.DisplayTick}/{session.Tick}{playing} · {session.PlaybackSpeed:0.#}×";
                }
                else
                {
                    string mode = session.IsLive ? "Live" : "Replay";
                    tickLabel.text =
                        $"Tick {session.DisplayTick}/{session.Tick} ({mode}{playing}) · {session.PlaybackSpeed:0.#}×";
                }
            }

            if (streamLabel != null)
            {
                streamLabel.text = session.IsOffline
                    ? "离线演示 · 无需后端"
                    : $"SSE: {session.StreamStatus}";
            }

            if (clockLabel != null)
            {
                int displayTick = session.DisplayTick;
                int day = Mathf.Max(1, (displayTick / 24) + 1);
                int hour = session.Hour;
                if (hour < 0 || hour > 23)
                {
                    hour = ((displayTick % 24) + 24) % 24;
                }

                clockLabel.text = $"第 {day} 天 · {hour:D2}:00";
            }

            if (playButton != null)
            {
                playButton.text = session.Playing ? "⏸" : "▶";
            }

            if (liveButton != null)
            {
                liveButton.text = session.IsOffline ? "末帧" : "Live";
            }

            if (nextStoryButton != null)
            {
                // Live scripted has no local story index yet — Offline / Replay only.
                bool storySeek = session.IsOffline || session.IsReplayActive;
                nextStoryButton.SetEnabled(storySeek);
                nextStoryButton.style.display = storySeek ? DisplayStyle.Flex : DisplayStyle.None;
                nextStoryButton.tooltip = storySeek
                    ? "跳到下一故事节拍（交互 / 世界事件 / 投票）"
                    : "下一故事仅用于 Offline / Replay（Live 请用推进 Tick）";
            }

            foreach ((string speedName, float value) in SpeedButtons)
            {
                Button button = document.rootVisualElement?.Q<Button>(speedName);
                button?.EnableInClassList("active", Mathf.Approximately(value, session.PlaybackSpeed));
            }

            RefreshSeekSlider();
            RefreshStoryBeat();
            RefreshTimelineStory();
            RefreshStatus();
        }

        private void RefreshStoryBeat()
        {
            if (storyBeatLabel == null || session == null)
            {
                return;
            }

            if (!session.IsOffline && !session.IsReplayActive)
            {
                storyBeatLabel.text = "";
                storyBeatLabel.style.display = DisplayStyle.None;
                return;
            }

            storyBeatLabel.style.display = DisplayStyle.Flex;
            string packName = session.IsOffline
                ? DemoPackIds.DisplayName(session.OfflinePackId)
                : "Replay";
            List<StoryBeatProgress.PulseMark> pulses = EnsurePulses();
            StoryBeatProgress.BarState bar = StoryBeatProgress.Resolve(
                packName, session.DisplayTick, pulses);
            storyBeatLabel.text = bar.Text;
            storyBeatLabel.tooltip = bar.OnPulse
                ? $"故事节拍 {bar.CurrentIndex}/{bar.TotalBeats}"
                : "日常 / 过渡拍 — 用「下一故事」跳到节拍";
        }

        private void RefreshTimelineStory(int? seekTick = null)
        {
            if (timelineStoryLabel == null || session == null)
            {
                return;
            }

            if (!session.IsOffline && !session.IsReplayActive)
            {
                timelineStoryLabel.text = "";
                timelineStoryLabel.style.display = DisplayStyle.None;
                return;
            }

            timelineStoryLabel.style.display = DisplayStyle.Flex;
            int tick = seekTick ?? session.DisplayTick;
            StoryBeatProgress.TimelineHint hint = StoryBeatProgress.ResolveTimeline(
                tick, EnsurePulses());
            timelineStoryLabel.text = hint.Combined;
            timelineStoryLabel.tooltip = hint.Combined;
        }

        private void RefreshSeekSlider()
        {
            if (seekSlider == null || session == null || seekSliderDragging)
            {
                return;
            }

            int high = Mathf.Max(1, session.Tick);
            seekSlider.lowValue = 1;
            seekSlider.highValue = high;
            int display = Mathf.Clamp(session.DisplayTick, 1, high);
            if (seekSlider.value != display)
            {
                seekSlider.SetValueWithoutNotify(display);
            }

            seekSlider.tooltip = StoryBeatProgress.TooltipForTick(display, EnsurePulses());
        }

        private void RefreshMetrics()
        {
            if (!bound || session == null)
            {
                return;
            }

            TickMetrics m = session.Metrics;
            if (m == null)
            {
                if (metricMood != null) metricMood.text = "情绪 —";
                if (metricTrade != null) metricTrade.text = "交易 —";
                if (metricRelation != null) metricRelation.text = "关系 —";
                if (metricPop != null) metricPop.text = "人口 —";
                return;
            }

            if (metricMood != null)
            {
                metricMood.text = $"情绪 {m.AvgMood:+0.00;-0.00;0.00}";
            }

            if (metricTrade != null)
            {
                metricTrade.text = $"交易 {m.TradeCount}·{m.TradeTotalAmount:0}";
            }

            if (metricRelation != null)
            {
                metricRelation.text = $"关系 {m.PositiveRelationRatio:0%}";
            }

            if (metricPop != null)
            {
                int pop = 0;
                if (m.PopulationByRegion != null)
                {
                    foreach (int n in m.PopulationByRegion.Values)
                    {
                        pop += n;
                    }
                }

                if (pop == 0)
                {
                    pop = session.Agents.Count;
                }

                string top = "";
                if (m.PopulationByRegion != null)
                {
                    string best = null;
                    int bestN = -1;
                    foreach (KeyValuePair<string, int> pair in m.PopulationByRegion)
                    {
                        if (pair.Value > bestN)
                        {
                            bestN = pair.Value;
                            best = pair.Key;
                        }
                    }

                    if (!string.IsNullOrEmpty(best))
                    {
                        top = $" ·{best}{bestN}";
                    }
                }

                metricPop.text = $"人口 {pop}{top}";
            }
        }

        private void RefreshModifiers()
        {
            if (!bound || modifierChips == null || session == null)
            {
                return;
            }

            modifierChips.Clear();
            List<WorldModifierChip> chips = WorldModifierChips.From(session.Modifiers);
            WorldModifierChips.AppendActiveEvents(chips, session.ActiveEvents);

            if (chips.Count == 0)
            {
                var empty = new Label("无活跃修饰");
                empty.AddToClassList("mod-chip");
                empty.AddToClassList("empty");
                modifierChips.Add(empty);
                return;
            }

            for (int i = 0; i < chips.Count; i++)
            {
                WorldModifierChip chip = chips[i];
                var label = new Label(chip.Label);
                label.AddToClassList("mod-chip");
                if (chip.Tone == ModifierChipTone.Warn)
                {
                    label.AddToClassList("warn");
                }
                else if (chip.Tone == ModifierChipTone.Positive)
                {
                    label.AddToClassList("positive");
                }

                modifierChips.Add(label);
            }
        }

        private void RefreshDecisions()
        {
            if (!bound || decisionsList == null || session == null)
            {
                return;
            }

            decisionsList.Clear();
            IReadOnlyList<SimDecision> decisions = session.Decisions;
            if (decisions.Count == 0)
            {
                var empty = new Label("暂无决策");
                empty.AddToClassList("observe-empty");
                decisionsList.Add(empty);
                return;
            }

            // Tick groups + story-first ranking; collapse move_to/闲逛 when the tick has story.
            List<DecisionTabRow> rows = DecisionSummary.BuildTabRows(decisions, maxRows: 40);
            if (rows.Count == 0)
            {
                var empty = new Label("暂无决策");
                empty.AddToClassList("observe-empty");
                decisionsList.Add(empty);
                return;
            }

            foreach (DecisionTabRow row in rows)
            {
                if (row.IsGroupHeader)
                {
                    var header = new Label(row.Text);
                    header.AddToClassList("observe-meta");
                    decisionsList.Add(header);
                    continue;
                }

                if (row.IsCollapsedMoves)
                {
                    decisionsList.Add(BuildCollapsedMovesRow(row.Text));
                    continue;
                }

                if (row.Decision != null)
                {
                    decisionsList.Add(BuildDecisionRow(row.Decision));
                }
            }
        }

        private VisualElement BuildDecisionRow(SimDecision decision)
        {
            var row = new VisualElement();
            row.AddToClassList("observe-row");

            string primary = DecisionSummary.FormatPrimaryLine(decision, session);
            var body = new Label(primary);
            body.AddToClassList("observe-summary");

            string metaText = DecisionSummary.FormatMetaLine(decision);
            var meta = new Label(metaText);
            meta.AddToClassList("observe-meta");

            // Primary line first (who · action · why); tick/type as secondary meta.
            row.Add(body);
            row.Add(meta);
            return row;
        }

        private static VisualElement BuildCollapsedMovesRow(string text)
        {
            var row = new VisualElement();
            row.AddToClassList("observe-row");

            var body = new Label(string.IsNullOrEmpty(text) ? "移动" : text);
            body.AddToClassList("observe-summary");
            row.Add(body);
            return row;
        }

        private void RefreshEvents()
        {
            if (!bound || eventsList == null || session == null)
            {
                return;
            }

            eventsList.Clear();

            int shown = 0;
            shown += AppendActiveInteractionRows(eventsList);

            IReadOnlyList<SimTickEvent> events = session.TickEvents;
            if (events.Count == 0 && shown == 0)
            {
                var empty = new Label("暂无事件");
                empty.AddToClassList("observe-empty");
                eventsList.Add(empty);
                return;
            }

            // Collapse consecutive same-tick rows; hide tick_started/ended noise.
            int lastTick = int.MinValue;
            int noiseSkipped = 0;
            foreach (SimTickEvent evt in events)
            {
                if (evt == null)
                {
                    continue;
                }

                if (SimEventFilters.IsTickNoise(evt.Type))
                {
                    noiseSkipped++;
                    continue;
                }

                if (shown >= 50)
                {
                    break;
                }

                if (evt.Tick != lastTick)
                {
                    var tickHeader = new Label($"── Tick {evt.Tick} ──");
                    tickHeader.AddToClassList("observe-meta");
                    eventsList.Add(tickHeader);
                    lastTick = evt.Tick;
                }

                eventsList.Add(BuildEventRow(evt));
                shown++;
            }

            if (shown == 0)
            {
                string hint = noiseSkipped > 0
                    ? "暂无故事事件（已折叠 tick 噪声）"
                    : "暂无事件";
                var empty = new Label(hint);
                empty.AddToClassList("observe-empty");
                eventsList.Add(empty);
            }
        }

        /// <summary>
        /// Pin current ActiveInteractions (dialogue / trade / vote already on the Offline pack)
        /// at the top of the Events tab — no new data, just surface what the world is doing now.
        /// </summary>
        private int AppendActiveInteractionRows(ScrollView list)
        {
            if (session == null || session.ActiveInteractions.Count == 0)
            {
                return 0;
            }

            int added = 0;
            var header = new Label("── 当前互动 ──");
            header.AddToClassList("observe-now-header");
            list.Add(header);

            foreach (KeyValuePair<string, ActiveInteraction> pair in session.ActiveInteractions)
            {
                ActiveInteraction ix = pair.Value;
                if (ix == null)
                {
                    continue;
                }

                var row = new VisualElement();
                row.AddToClassList("observe-row");

                string kind = string.IsNullOrEmpty(ix.Kind) ? "interaction" : ix.Kind;
                var meta = new Label($"{kind} · tick {ix.Tick}");
                meta.AddToClassList("observe-meta");

                string summary = string.IsNullOrEmpty(ix.Summary) ? kind : ix.Summary;
                var body = new Label(summary);
                body.AddToClassList("observe-summary");

                row.Add(meta);
                row.Add(body);

                string transcript = InteractionModel.FormatTranscript(ix.Transcript);
                if (!string.IsNullOrWhiteSpace(transcript))
                {
                    var detail = new Label(transcript);
                    detail.AddToClassList("observe-detail");
                    row.Add(detail);
                }

                list.Add(row);
                added++;
            }

            return added;
        }

        private static VisualElement BuildEventRow(SimTickEvent evt)
        {
            var row = new VisualElement();
            row.AddToClassList("observe-row");

            string who = string.IsNullOrEmpty(evt.AgentId) ? "" : $" · {evt.AgentId}";
            var meta = new Label($"{evt.Type}{who}");
            meta.AddToClassList("observe-meta");

            string summary = string.IsNullOrEmpty(evt.Summary) ? evt.Type : evt.Summary;
            var body = new Label(summary);
            body.AddToClassList("observe-summary");

            row.Add(meta);
            row.Add(body);

            if (!string.IsNullOrWhiteSpace(evt.Detail))
            {
                var detail = new Label(evt.Detail);
                detail.AddToClassList("observe-detail");
                row.Add(detail);
            }

            return row;
        }

        private void RefreshResidents()
        {
            if (!bound || session == null || residentsList == null)
            {
                return;
            }

            residentsList.Clear();
            List<ResidentView> residents = TownResidents.Build(session);
            string selectedId = session.SelectedAgentId;

            foreach (ResidentView resident in residents)
            {
                residentsList.Add(BuildResidentRow(resident, resident.AgentId == selectedId));
            }

            RefreshDetail(selectedId, residents);
            birdseyeButton?.SetEnabled(!string.IsNullOrEmpty(session.TrackedAgentId));
        }

        private VisualElement BuildResidentRow(ResidentView resident, bool selected)
        {
            var row = new VisualElement { name = $"resident-{resident.AgentId}" };
            row.AddToClassList("resident-row");
            if (selected)
            {
                row.AddToClassList("selected");
            }

            var nameLabel = new Label(resident.Name);
            nameLabel.AddToClassList("resident-name");

            string meta = resident.Role;
            if (!string.IsNullOrEmpty(resident.Location))
            {
                meta = string.IsNullOrEmpty(meta) ? resident.Location : $"{meta} · {resident.Location}";
            }

            var metaLabel = new Label(meta);
            metaLabel.AddToClassList("resident-meta");

            row.Add(nameLabel);
            row.Add(metaLabel);
            row.RegisterCallback<ClickEvent>(_ => SelectResident(resident.AgentId));
            return row;
        }

        private void SelectResident(string agentId)
        {
            bool alreadySelected = session.SelectedAgentId == agentId;
            session.SetSelectedAgent(alreadySelected ? null : agentId);
            session.SetTrackedAgent(alreadySelected ? null : agentId);
            if (alreadySelected)
            {
                TownCamera cam = FindFirstObjectByType<TownCamera>();
                cam?.Frame();
            }
        }

        private void RefreshDetail(string selectedId, List<ResidentView> residents)
        {
            if (residentDetail == null)
            {
                return;
            }

            residentDetail.Clear();

            ResidentView selected = null;
            if (!string.IsNullOrEmpty(selectedId))
            {
                foreach (ResidentView resident in residents)
                {
                    if (resident.AgentId == selectedId)
                    {
                        selected = resident;
                        break;
                    }
                }
            }

            if (selected == null)
            {
                var hint = new Label("选择一位居民查看人设与状态。");
                hint.AddToClassList("detail-hint");
                residentDetail.Add(hint);
                return;
            }

            var title = new Label(selected.Name);
            title.AddToClassList("detail-title");
            residentDetail.Add(title);

            var sub = new Label(string.IsNullOrEmpty(selected.Location)
                ? selected.Role
                : $"{selected.Role} · {selected.Location}");
            sub.AddToClassList("detail-sub");
            residentDetail.Add(sub);

            if (!string.IsNullOrEmpty(selected.Bio))
            {
                var bio = new Label(selected.Bio);
                bio.AddToClassList("detail-bio");
                residentDetail.Add(bio);
            }

            residentDetail.Add(DetailLine("目标", string.IsNullOrEmpty(selected.Goal) ? "—" : selected.Goal));
            if (selected.HasLiveState)
            {
                residentDetail.Add(DetailLine("情绪", $"{AgentDisplayLabels.MoodLabel(selected.Mood)} ({selected.Mood:0.00})"));
                residentDetail.Add(DetailLine("金钱", selected.Money.ToString("0")));
                residentDetail.Add(DetailLine("活动", string.IsNullOrEmpty(selected.Activity) ? "—" : selected.Activity));
                if (!string.IsNullOrEmpty(selected.LastThought))
                {
                    residentDetail.Add(DetailLine("此刻想法", selected.LastThought));
                }
            }

            AddRelationships(selected, residents);

            AddTrait(selected, "开放性", selected.BigFive.Openness);
            AddTrait(selected, "尽责性", selected.BigFive.Conscientiousness);
            AddTrait(selected, "外向性", selected.BigFive.Extraversion);
            AddTrait(selected, "宜人性", selected.BigFive.Agreeableness);
            AddTrait(selected, "神经质", selected.BigFive.Neuroticism);
        }

        private void AddRelationships(ResidentView selected, List<ResidentView> residents)
        {
            if (selected?.Relationships == null || selected.Relationships.Count == 0)
            {
                return;
            }

            var heading = new Label("关系");
            heading.AddToClassList("detail-section");
            residentDetail.Add(heading);

            var ordered = new List<KeyValuePair<string, double>>(selected.Relationships);
            ordered.Sort((a, b) =>
            {
                int byAbs = Math.Abs(b.Value).CompareTo(Math.Abs(a.Value));
                return byAbs != 0 ? byAbs : string.CompareOrdinal(a.Key, b.Key);
            });

            int shown = 0;
            foreach (KeyValuePair<string, double> pair in ordered)
            {
                if (string.IsNullOrEmpty(pair.Key) || shown >= 6)
                {
                    continue;
                }

                string name = ResolveResidentName(pair.Key, residents);
                residentDetail.Add(DetailLine(name, FormatRelation(pair.Value)));
                shown++;
            }
        }

        private static string ResolveResidentName(string agentId, List<ResidentView> residents)
        {
            if (residents != null)
            {
                foreach (ResidentView r in residents)
                {
                    if (r != null && r.AgentId == agentId && !string.IsNullOrEmpty(r.Name))
                    {
                        return r.Name;
                    }
                }
            }

            LocalPersona local = TownPersonas.Get(agentId);
            if (local != null && !string.IsNullOrEmpty(local.Name))
            {
                return local.Name;
            }

            return agentId;
        }

        private static string FormatRelation(double value)
        {
            string tone = value >= 0.35 ? "亲近"
                : value >= 0.1 ? "友好"
                : value >= -0.1 ? "一般"
                : value >= -0.35 ? "冷淡"
                : "对立";
            return $"{tone} ({value:+0.00;-0.00;0.00})";
        }

        private static VisualElement DetailLine(string key, string value)
        {
            var line = new VisualElement();
            line.AddToClassList("detail-line");

            var keyLabel = new Label(key);
            keyLabel.AddToClassList("detail-key");
            var valueLabel = new Label(value);
            valueLabel.AddToClassList("detail-value");

            line.Add(keyLabel);
            line.Add(valueLabel);
            return line;
        }

        private void AddTrait(ResidentView _, string label, double value)
        {
            var row = new VisualElement();
            row.AddToClassList("trait-row");

            var labelEl = new Label(label);
            labelEl.AddToClassList("trait-label");

            var track = new VisualElement();
            track.AddToClassList("trait-track");
            var fill = new VisualElement();
            fill.AddToClassList("trait-fill");
            fill.style.width = Length.Percent(Mathf.Clamp01((float)value) * 100f);
            track.Add(fill);

            row.Add(labelEl);
            row.Add(track);
            residentDetail.Add(row);
        }

    }
}
