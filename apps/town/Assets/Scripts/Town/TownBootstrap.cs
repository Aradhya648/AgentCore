using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using AgentTown.Show;
using AgentTown.Simulation;
using AgentTown.UI;
using UnityEngine;
using UnityEngine.UIElements;

namespace AgentTown.Town
{
    /// <summary>
    /// Top-level scene assembler (§7 Bootstrap, §15.2). The single MonoBehaviour that needs to be
    /// placed in the Town scene — everything else is spawned in code. It resolves the launch
    /// config (§8), configures the <see cref="SimulationSession"/> singleton, builds the town +
    /// NavMesh, spawns/seeds NPCs, frames the bird's-eye camera, wires the UI to the session, and
    /// pumps <see cref="SimulationSession.Update"/> every frame. On a <c>--run-id</c> it resumes the
    /// run (manifest + SSE + first frame), mirroring the retired UE <c>TownGameMode</c>.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class TownBootstrap : MonoBehaviour
    {
        [Header("UI (assign in Editor — see EDITOR-WIRING.md)")]
        [Tooltip("TownHud.uxml — the observer panel layout.")]
        [SerializeField] private VisualTreeAsset hudUxml;

        [Tooltip("A PanelSettings asset for the runtime UI Toolkit panel.")]
        [SerializeField] private PanelSettings hudPanelSettings;

        [Tooltip("Optional: TownHud.uss, applied if the UXML does not link it.")]
        [SerializeField] private StyleSheet hudStyleSheet;

        /// <summary>Bridge pack id for programme-mode shoots (`?episode=3&amp;shoot=1`).</summary>
        public const string ShowEpisodePackId = "episode_3";

        /// <summary>
        /// Programme shoot landmark: day-market 「香料摊」 beat (caption + follow_pair shot).
        /// Keep in sync with the episode_3 entry in scripts/shoot-webgl-demo.mjs.
        /// </summary>
        public const int ShowShootLandmarkTick = 24;

        private SimulationSession session;
        private string launchPackId = DemoPackIds.PriceSurge;
        private bool shootMode;
        private int lastPublishedDemoTick = -1;
        private Label bootStatusLabel;
        private VisualElement bootOverlay;

        private async void Start()
        {
            try
            {
                await BootAsync();
            }
            catch (Exception e)
            {
                SetBootStatus($"启动失败：{e.Message}");
                Debug.LogException(e);
            }
        }

        private void Update()
        {
            session?.Update(Time.deltaTime);
            PublishDemoTickIfNeeded();
        }

        private void OnDestroy()
        {
            // Stop the live stream when the town is torn down.
            session?.Reset();
        }

#if UNITY_EDITOR
        private void OnDrawGizmos()
        {
            // Edit-mode footprint so Scene 视图不是「完全空白」— 真实几何仍在 Play 时生成。
            Gizmos.color = new Color(0.25f, 0.72f, 0.35f, 0.35f);
            Vector3 ground = new Vector3(TownVisualLayout.GroundSize.x, 0.05f, TownVisualLayout.GroundSize.y);
            Gizmos.DrawCube(Vector3.zero, ground);

            Gizmos.color = new Color(1f, 0.85f, 0.2f, 0.9f);
            Vector3 center = WireCoordinateTransform.ToUnity(
                TownVisualLayout.ViewCenterWire.x,
                TownVisualLayout.ViewCenterWire.y,
                TownVisualLayout.ViewCenterWire.z);
            Gizmos.DrawWireSphere(center, 2f);
        }
#endif

        private async Task BootAsync()
        {
            // Spec §7 / §14 #5: aim for ≥30 FPS watch floor (uncap vsync when possible).
            Application.targetFrameRate = 60;
            QualitySettings.vSyncCount = 0;
            TownWatchPerf.ApplyBootPolicy();

            AgentTownLaunchConfig config = AgentTownLaunchConfig.Load();
            launchPackId = config.PackId;
            shootMode = config.Shoot;
            if (shootMode)
            {
                AgentTownDemoBridge.SetShootMode(true);
            }

            session = SimulationSession.Instance;
            session.Configure(config.ApiBase, config.AccessToken, config.RunId);
            session.SetStatusMessage("正在加载小镇…");

            await TownPersonas.LoadAsync();
            // Offline story SoT (Fixtures/demo-story-packs.json); Build falls back if missing.
            await DemoStoryPackCatalog.EnsureLoadedAsync();

            Material npcMaterial = CreatePlaceholderMaterial("TownNpc");
            TownBuilder builder = SpawnBuilder();
            await builder.BuildAsync();

            TownNpcManager npcManager = SpawnNpcManager(npcMaterial);
            npcManager.SeedFromPersonas(builder.RegionAnchors);
            TownWatchPerf.SimplifySceneForWebGl(npcManager.transform);

            Light sun = EnsureLighting();
            EnsureDayNight(sun);
            TownWatchPerf.StripAllLightShadows();
            EnsureObservationLayers();
            FrameCamera();
            WireHud();
            EnsureShowMode();
            SetBootStatus("正在烘焙演示…");

            if (config.ShouldAutoShowEpisode)
            {
                await StartShowEpisodeAsync(config.Episode);
            }
            else if (config.ShouldAutoOfflineDemo)
            {
                await StartOfflineDemoAsync(config.PackId);
            }
            else if (!string.IsNullOrEmpty(config.RunId))
            {
                HideBootOverlay();
                ResumeLaunchRun();
            }
            else
            {
                // Credentials present but no run — still prefer a watchable surface.
                await StartOfflineDemoAsync(config.PackId);
            }
        }

        private TownBuilder SpawnBuilder()
        {
            var go = new GameObject("TownBuilder");
            go.transform.SetParent(transform, false);
            return go.AddComponent<TownBuilder>();
        }

        private TownNpcManager SpawnNpcManager(Material npcMaterial)
        {
            var go = new GameObject("TownNpcManager");
            go.transform.SetParent(transform, false);
            var manager = go.AddComponent<TownNpcManager>();
            manager.Bind(session, npcMaterial);
            return manager;
        }

        private Light EnsureLighting()
        {
            foreach (Light existing in FindObjectsByType<Light>(FindObjectsSortMode.None))
            {
                if (existing.type == LightType.Directional)
                {
                    ApplyWatchShadowPolicy(existing);
                    return existing;
                }
            }

            var lightGo = new GameObject("TownSun");
            lightGo.transform.SetParent(transform, false);
            lightGo.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
            Light sun = lightGo.AddComponent<Light>();
            sun.type = LightType.Directional;
            sun.color = new Color(1f, 0.96f, 0.9f);
            sun.intensity = 1.1f;
            ApplyWatchShadowPolicy(sun);
            return sun;
        }

        private static void ApplyWatchShadowPolicy(Light sun)
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            // WebGL: soft shadows are a common FPS cliff; keep lighting without the cost.
            sun.shadows = LightShadows.None;
#else
            if (sun.shadows == LightShadows.None)
            {
                sun.shadows = LightShadows.Soft;
            }
#endif
        }

        private void EnsureDayNight(Light sun)
        {
            TownDayNight dayNight = GetComponent<TownDayNight>();
            if (dayNight == null)
            {
                dayNight = gameObject.AddComponent<TownDayNight>();
            }

            dayNight.Bind(session, sun);
            RenderSettings.sun = sun;
        }

        private void EnsureObservationLayers()
        {
            TownRegionHeatmap heatmap = GetComponent<TownRegionHeatmap>();
            if (heatmap == null)
            {
                heatmap = gameObject.AddComponent<TownRegionHeatmap>();
            }

            heatmap.Bind(session);

            TownInteractionOverlays overlays = GetComponent<TownInteractionOverlays>();
            if (overlays == null)
            {
                overlays = gameObject.AddComponent<TownInteractionOverlays>();
            }

            overlays.Bind(session);

            TownWorldEventFeedback worldFeedback = GetComponent<TownWorldEventFeedback>();
            if (worldFeedback == null)
            {
                worldFeedback = gameObject.AddComponent<TownWorldEventFeedback>();
            }

            worldFeedback.Bind(session);
        }

        private void FrameCamera()
        {
            Camera cam = Camera.main;
            if (cam == null)
            {
                var camGo = new GameObject("TownCamera") { tag = "MainCamera" };
                cam = camGo.AddComponent<Camera>();
                camGo.AddComponent<AudioListener>();
            }

            TownCamera townCamera = cam.GetComponent<TownCamera>();
            if (townCamera == null)
            {
                townCamera = cam.gameObject.AddComponent<TownCamera>();
            }

            cam.allowHDR = false;
            cam.allowMSAA = false;
            // Built-in skybox background — infinite, always drawn behind all geometry.
            cam.clearFlags = CameraClearFlags.Skybox;
            cam.farClipPlane = Mathf.Max(cam.farClipPlane, 400f);
            // Mid framing: district + surroundings — neither face-to-face nor far sand-table.
            cam.fieldOfView = shootMode ? 50f : 52f;
            townCamera.Bind(session);
        }

        private void WireHud()
        {
            if (hudUxml != null && hudPanelSettings != null)
            {
                // Build inactive so UIDocument.OnEnable sees the assets before constructing the tree.
                var uiGo = new GameObject("TownHud");
                uiGo.transform.SetParent(transform, false);
                uiGo.SetActive(false);

                var document = uiGo.AddComponent<UIDocument>();
                document.panelSettings = hudPanelSettings;
                document.visualTreeAsset = hudUxml;

                TownHudController controller = uiGo.AddComponent<TownHudController>();
                TownNameplateHud nameplates = uiGo.AddComponent<TownNameplateHud>();
                uiGo.AddComponent<ShowHudController>();
                uiGo.SetActive(true);
                controller.Bind(session);
                nameplates.Bind(session);
                bootOverlay = document.rootVisualElement?.Q<VisualElement>("boot-overlay");
                bootStatusLabel = document.rootVisualElement?.Q<Label>("boot-status-label");
                SetBootStatus("正在加载小镇…");
                return;
            }

            TownHudController existing = FindFirstObjectByType<TownHudController>();
            if (existing != null)
            {
                existing.Bind(session);
                TownNameplateHud plates = existing.GetComponent<TownNameplateHud>()
                    ?? existing.gameObject.AddComponent<TownNameplateHud>();
                plates.Bind(session);
                return;
            }

            Debug.LogWarning(
                "[AgentTown] HUD not wired — assign hudUxml + hudPanelSettings on TownBootstrap, " +
                "or add a UIDocument + TownHudController to the scene (see EDITOR-WIRING.md).");
        }

        /// <summary>HUD / CLI entry: load local personas + region anchors into an offline demo pack.</summary>
        public void StartOfflineDemo(string packId = null)
        {
            _ = StartOfflineDemoAsync(packId);
        }

        /// <summary>Left-rail「节目」/ deep link entry for episode 3 offline programme mode.</summary>
        public void StartShowEpisode3()
        {
            _ = StartShowEpisodeAsync(3);
        }

        public async Task StartShowEpisodeAsync(int episodeNo)
        {
            EnsureShowMode();
            ShowModeController show = GetComponent<ShowModeController>()
                ?? FindFirstObjectByType<ShowModeController>();
            if (show == null)
            {
                Debug.LogWarning("[AgentTown] ShowModeController missing");
                return;
            }

            SetBootStatus($"正在载入第 {episodeNo} 期…");
            if (episodeNo == 3)
            {
                await show.EnterEpisode3Async();
            }
            else
            {
                Debug.LogWarning($"[AgentTown] Episode {episodeNo} not bundled yet — only episode 3 offline");
                await show.EnterEpisode3Async();
            }

            if (shootMode)
            {
                show.EnterShootFrame(ShowShootLandmarkTick);
            }

            HideBootOverlay();

            // Same Playwright probe contract as Offline packs (shoot gate + serve smoke).
            AgentTownDemoBridge.SetOfflineReady(
                ShowEpisodePackId,
                show.Manifest?.Title ?? $"第 {episodeNo} 期");
            PublishDemoTickIfNeeded(force: true);
        }

        private void EnsureShowMode()
        {
            ShowModeController show = GetComponent<ShowModeController>();
            if (show == null)
            {
                show = gameObject.AddComponent<ShowModeController>();
            }

            CinematicDirector director = GetComponent<CinematicDirector>();
            if (director == null)
            {
                director = gameObject.AddComponent<CinematicDirector>();
            }

            TownHudController townHud = FindFirstObjectByType<TownHudController>();
            ShowHudController showHud = townHud != null
                ? townHud.GetComponent<ShowHudController>()
                : FindFirstObjectByType<ShowHudController>();
            if (townHud != null && showHud == null)
            {
                showHud = townHud.gameObject.AddComponent<ShowHudController>();
            }

            show.Bind(session, showHud, townHud, director);
        }

        /// <summary>Async Offline entry — ensures JSON story SoT is loaded before baking frames.</summary>
        public async Task StartOfflineDemoAsync(string packId = null)
        {
            string resolved = DemoPackIds.Normalize(
                string.IsNullOrEmpty(packId) ? launchPackId : packId);
            launchPackId = resolved;
            SetBootStatus($"正在烘焙「{DemoPackIds.DisplayName(resolved)}」…");

            await DemoStoryPackCatalog.EnsureLoadedAsync();

            Dictionary<string, WireVec3> regions = await RegionPositions.LoadAsync();
            OfflineDemoPack pack = OfflineDemoBuilder.Build(
                TownPersonas.All, regions, packId: resolved);
            session.EnterOfflineDemo(pack);

            int seekTick = ResolveOfflineSeekTick(pack, resolved);
            if (seekTick > 1)
            {
                session.SeekTick(seekTick);
            }

            if (shootMode)
            {
                // Landmark seek jumps many ticks — snap NPCs so bubbles/trade icons sit on cue.
                TownNpcManager npcs = FindFirstObjectByType<TownNpcManager>();
                npcs?.SnapAllToGoals();
                FrameShootLandmark(resolved, regions);
            }

            // Shoot freezes on the landmark interaction so overlays stay visible for PNG.
            session.SetPlaying(!shootMode);
            HideBootOverlay();
            // WebGL shoot / Playwright probe (UI Toolkit text is not in the DOM).
            AgentTownDemoBridge.SetOfflineReady(resolved, DemoPackIds.DisplayName(resolved));
            PublishDemoTickIfNeeded(force: true);

            if (!shootMode)
            {
                TownHudController hud = FindFirstObjectByType<TownHudController>();
                hud?.ShowPackIntro(resolved);
            }
        }

        /// <summary>
        /// Aim bird camera at the pack landmark so story overlays stay on-screen.
        /// Keep look-at on the landmark (not biased to core) — periphery districts are where
        /// the scripted gather happens; the skybox fills the map-edge rim.
        /// </summary>
        private void FrameShootLandmark(string packId, Dictionary<string, WireVec3> anchors)
        {
            string regionId = DemoPackIds.ShootLandmarkRegion(packId);
            float wireX;
            float wireY;
            float wireZ;

            if (anchors != null && anchors.TryGetValue(regionId, out WireVec3 wire))
            {
                wireX = (float)wire.X;
                wireY = (float)wire.Y;
                wireZ = (float)wire.Z;
            }
            else
            {
                // Fallback: Unity anchors from TownBuilder (already transformed).
                TownBuilder builder = FindFirstObjectByType<TownBuilder>();
                if (builder == null
                    || !builder.RegionAnchors.TryGetValue(regionId, out Vector3 unity))
                {
                    return;
                }

                // Inverse of WireCoordinateTransform.ToUnity: (x,y,-z).
                wireX = unity.x;
                wireY = 0f;
                wireZ = -unity.z;
            }

            Camera cam = Camera.main;
            TownCamera townCamera = cam != null ? cam.GetComponent<TownCamera>() : null;
            if (townCamera == null)
            {
                return;
            }

            townCamera.FrameOnWire(
                wireX,
                wireY,
                wireZ,
                TownVisualLayout.BirdZoomShootDistance);
            // Re-assert skybox clear flags after shoot framing rebinds the camera pose.
            TownDayNight dayNight = GetComponent<TownDayNight>();
            if (dayNight != null)
            {
                dayNight.RefreshSky();
            }
        }

        /// <summary>
        /// Normal watch: first story pulse. Shoot: pack landmark (图书馆 / 工坊 / …).
        /// </summary>
        private int ResolveOfflineSeekTick(OfflineDemoPack pack, string packId)
        {
            if (shootMode)
            {
                return DemoPackIds.ShootLandmarkTick(packId);
            }

            if (pack?.Interactions != null && pack.Interactions.Count > 0)
            {
                return pack.Interactions[0].Tick;
            }

            return 1;
        }

        private void PublishDemoTickIfNeeded(bool force = false)
        {
            if (session == null)
            {
                return;
            }

            int tick = session.DisplayTick;
            if (!force && tick == lastPublishedDemoTick)
            {
                return;
            }

            lastPublishedDemoTick = tick;
            AgentTownDemoBridge.SetTick(tick);
        }

        private void SetBootStatus(string message)
        {
            session?.SetStatusMessage(message);
            if (bootStatusLabel != null)
            {
                bootStatusLabel.text = message;
            }

            if (bootOverlay != null)
            {
                bootOverlay.RemoveFromClassList("hidden");
            }
        }

        private void HideBootOverlay()
        {
            if (bootOverlay != null)
            {
                bootOverlay.AddToClassList("hidden");
            }
        }

        private void ResumeLaunchRun()
        {
            // RunId is already set via Configure; fetch manifest + connect SSE, then a first frame.
            session.BootstrapActiveRun();
            _ = session.FetchLiveTickAsync(1);
        }

        private static Material CreatePlaceholderMaterial(string name)
        {
            Shader shader =
                Shader.Find("Universal Render Pipeline/Lit")
                ?? Shader.Find("Universal Render Pipeline/Unlit")
                ?? Shader.Find("Standard")
                ?? Shader.Find("Unlit/Color")
                ?? Shader.Find("Sprites/Default")
                ?? Shader.Find("UI/Default");
            if (shader == null)
            {
                Debug.LogWarning($"[AgentTown] No shader for material '{name}' — using null material");
                return null;
            }

            return new Material(shader) { name = name };
        }

#if UNITY_EDITOR
        /// <summary>Editor setup assigns HUD assets so they persist in the scene YAML.</summary>
        internal void ConfigureHudAssets(
            VisualTreeAsset uxml, PanelSettings panelSettings, StyleSheet styleSheet)
        {
            hudUxml = uxml;
            hudPanelSettings = panelSettings;
            hudStyleSheet = styleSheet;
        }
#endif
    }
}
