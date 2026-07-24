using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using AgentTown.Simulation;
using AgentTown.Town;
using AgentTown.UI;
using UnityEngine;

namespace AgentTown.Show
{
    public enum ShowFace
    {
        Landing,
        Playback,
        Quiz,
        EpisodeEnd,
        SeasonEnd,
    }

    /// <summary>
    /// Programme-mode session: five faces, offline episode playback via
    /// <see cref="SimulationSession.EnterOfflineDemo"/> / ApplySnapshot, cinematic shots,
    /// quiz interrupt, reveal, and episode-end highlights.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class ShowModeController : MonoBehaviour
    {
        public static ShowModeController Instance { get; private set; }

        private SimulationSession session;
        private EpisodeManifest manifest;
        private CinematicDirector director;
        private ShowHudController hud;
        private TownHudController observatoryHud;
        private ShowFace face = ShowFace.Landing;
        private bool active;
        private bool quizResolved;
        private string quizPick;
        private string monologueWho;
        private List<EpisodeRelationHint> relationHints = new();
        private int lastTick = -1;
        private bool pendingEpisodeEnd;

        public bool IsActive => active;
        public ShowFace Face => face;
        public EpisodeManifest Manifest => manifest;
        public string QuizPick => quizPick;
        public bool QuizCorrect =>
            !string.IsNullOrEmpty(quizPick)
            && manifest?.Quiz != null
            && string.Equals(quizPick, manifest.Quiz.Answer, StringComparison.Ordinal);

        public event Action OnFaceChanged;
        public event Action OnOverlaysChanged;

        private void Awake()
        {
            Instance = this;
        }

        private void OnDestroy()
        {
            if (Instance == this)
            {
                Instance = null;
            }

            if (session != null)
            {
                session.OnSnapshotApplied -= HandleSnapshot;
                session.OnPlaybackChanged -= HandlePlayback;
            }
        }

        public void Bind(
            SimulationSession target,
            ShowHudController showHud,
            TownHudController townHud,
            CinematicDirector cinematic)
        {
            if (session != null)
            {
                session.OnSnapshotApplied -= HandleSnapshot;
                session.OnPlaybackChanged -= HandlePlayback;
            }

            session = target;
            hud = showHud;
            observatoryHud = townHud;
            director = cinematic;
            session.OnSnapshotApplied += HandleSnapshot;
            session.OnPlaybackChanged += HandlePlayback;
            hud?.Bind(this);
        }

        public async Task EnterEpisode3Async()
        {
            EpisodeManifest loaded = await EpisodeManifestLoader.LoadEpisode3Async();
            if (!EpisodeManifestLoader.Validate(loaded, out string error))
            {
                Debug.LogWarning($"[AgentTown] Show mode: invalid episode-3 manifest ({error})");
                return;
            }

            await EnterAsync(loaded);
        }

        public async Task EnterAsync(EpisodeManifest episode)
        {
            if (episode == null || session == null)
            {
                return;
            }

            manifest = episode;
            quizResolved = false;
            quizPick = null;
            monologueWho = episode.Quiz?.Focus;
            relationHints = new List<EpisodeRelationHint>();
            pendingEpisodeEnd = false;
            lastTick = -1;
            active = true;

            Dictionary<string, WireVec3> regions = await RegionPositions.LoadAsync();
            OfflineDemoPack pack = OfflineShowBuilder.Build(episode, regions);
            session.EnterOfflineDemo(pack);
            session.SetPlaying(false);

            TownCamera townCamera = FindFirstObjectByType<TownCamera>();
            TownNpcManager npcs = FindFirstObjectByType<TownNpcManager>();
            if (director != null)
            {
                director.Bind(episode, session, townCamera, npcs);
                director.SetFreeLook(false);
            }

            // Prefer cast identity colours on first spawn.
            if (npcs != null)
            {
                npcs.SnapAllToGoals();
            }

            observatoryHud?.SetObservatoryChromeVisible(false);
            hud?.SetVisible(true);
            SetFace(ShowFace.Landing);
            session.SetStatusMessage($"节目模式 — {episode.Title}");
        }

        public void ExitShowMode()
        {
            if (!active)
            {
                return;
            }

            active = false;
            session?.SetPlaying(false);
            director?.Unbind();
            hud?.SetVisible(false);
            observatoryHud?.SetObservatoryChromeVisible(true);
            SetFace(ShowFace.Landing);
            manifest = null;
            session?.SetStatusMessage("已退出节目模式");
        }

        public void StartPlaybackFromLanding()
        {
            if (!active || manifest == null)
            {
                return;
            }

            quizResolved = false;
            quizPick = null;
            pendingEpisodeEnd = false;
            SetFace(ShowFace.Playback);
            int start = manifest.TickRange?.Start ?? 0;
            session.SeekTick(start);
            session.SetPlaying(true);
        }

        /// <summary>
        /// Headless shoot: skip Landing, freeze playback on the landmark tick and apply
        /// its manifest shot so captions/cast are on-frame for the PNG gate.
        /// </summary>
        public void EnterShootFrame(int tick)
        {
            if (!active || manifest == null || session == null)
            {
                return;
            }

            quizResolved = true; // a frozen shoot frame must not be interrupted by the quiz face
            SetFace(ShowFace.Playback);
            session.SeekTick(tick);
            session.SetPlaying(false);

            TownNpcManager npcs = FindFirstObjectByType<TownNpcManager>();
            npcs?.SnapAllToGoals();

            EpisodeShot shot = EpisodeManifestLoader.ShotAtTick(manifest, tick);
            if (shot != null)
            {
                director?.ApplyShotImmediate(shot);
            }

            OnOverlaysChanged?.Invoke();
        }

        public void TogglePause()
        {
            if (face != ShowFace.Playback || session == null)
            {
                return;
            }

            session.SetPlaying(!session.Playing);
        }

        public void SetSpeed(float speed) => session?.SetPlaybackSpeed(speed);

        public void ToggleFreeLook()
        {
            if (director == null)
            {
                return;
            }

            director.SetFreeLook(!director.IsFreeLook);
            OnOverlaysChanged?.Invoke();
        }

        public void ReturnToDirector()
        {
            director?.ReturnToDirector();
            OnOverlaysChanged?.Invoke();
        }

        public void CycleMonologueFocus()
        {
            if (ShowCast.Members.Length == 0)
            {
                return;
            }

            int idx = 0;
            for (int i = 0; i < ShowCast.Members.Length; i++)
            {
                if (ShowCast.Members[i].Id == monologueWho)
                {
                    idx = (i + 1) % ShowCast.Members.Length;
                    break;
                }
            }

            monologueWho = ShowCast.Members[idx].Id;
            OnOverlaysChanged?.Invoke();
        }

        public void SetMonologueWho(string agentId)
        {
            monologueWho = agentId;
            OnOverlaysChanged?.Invoke();
        }

        public void SubmitQuizPick(string optionId)
        {
            if (face != ShowFace.Quiz || string.IsNullOrEmpty(optionId))
            {
                return;
            }

            quizPick = optionId;
            quizResolved = true;
            SetFace(ShowFace.Playback);
            int resume = manifest.Quiz?.InsertAt?.Tick ?? session.DisplayTick;
            // Advance into ceremony / reveal after quiz beat.
            session.SeekTick(Mathf.Max(resume + 1, resume));
            session.SetPlaying(true);
        }

        public void JumpToHighlight(EpisodeHighlight highlight)
        {
            if (highlight == null || manifest == null || session == null)
            {
                return;
            }

            EpisodeShot shot = EpisodeManifestLoader.FindShotById(manifest, highlight.ShotId);
            int tick = shot?.TickAt
                       ?? EpisodeManifestLoader.FindOverlayById(manifest, highlight.OverlayId)?.TickAt
                       ?? session.DisplayTick;
            SetFace(ShowFace.Playback);
            session.SeekTick(tick);
            session.SetPlaying(true);
            if (shot != null)
            {
                director?.ApplyShotImmediate(shot);
            }
        }

        public void ShowSeasonEndPlaceholder() => SetFace(ShowFace.SeasonEnd);

        public void ReturnToEpisodeEnd() => SetFace(ShowFace.EpisodeEnd);

        public void BackToLanding() => SetFace(ShowFace.Landing);

        public PlaybackHudState CapturePlaybackHud()
        {
            var state = new PlaybackHudState
            {
                Title = manifest?.Title ?? "",
                RuleLine = manifest?.RuleLine ?? "",
                SegmentLabel = EpisodeManifestLoader.SegmentAtTick(manifest, session?.DisplayTick ?? 0)?.Label
                               ?? "",
                Playing = session != null && session.Playing,
                Speed = session?.PlaybackSpeed ?? 1f,
                FreeLook = director != null && director.IsFreeLook,
                MonologueWho = monologueWho,
                MonologueName = ShowCast.DisplayName(monologueWho),
                RelationHints = relationHints,
            };

            if (session == null || manifest == null)
            {
                return state;
            }

            int tick = session.DisplayTick;
            foreach (EpisodeOverlayView view in EpisodeManifestLoader.FlattenOverlays(manifest))
            {
                if (view?.TickAt == null || view.TickAt.Value > tick)
                {
                    continue;
                }

                // Keep latest of each spoken kind for the HUD layers.
                if (view.Kind == "line" || view.Kind == "action" || view.Kind == "narration"
                    || view.Kind == "title_card")
                {
                    if (state.CaptionTick <= (view.TickAt ?? -1))
                    {
                        state.CaptionTick = view.TickAt ?? 0;
                        state.CaptionKind = view.Kind;
                        state.CaptionWho = view.Who;
                        state.CaptionText = view.Kind == "title_card"
                            ? (string.IsNullOrEmpty(view.Sub) ? view.Text : $"{view.Text}\n{view.Sub}")
                            : view.Text;
                    }
                }

                if (view.Kind == "monologue"
                    && (string.IsNullOrEmpty(monologueWho) || view.Who == monologueWho)
                    && state.MonologueTick <= (view.TickAt ?? -1))
                {
                    state.MonologueTick = view.TickAt ?? 0;
                    state.MonologueText = view.Text;
                    state.MonologueWho = view.Who;
                    state.MonologueName = ShowCast.DisplayName(view.Who);
                }

                if (view.Kind == "relation" && view.TickAt.Value <= tick)
                {
                    relationHints = view.Hints ?? new List<EpisodeRelationHint>();
                    state.RelationHints = relationHints;
                }
            }

            return state;
        }

        private void Update()
        {
            if (!active || face != ShowFace.Playback || session == null || manifest == null)
            {
                return;
            }

            int tick = session.DisplayTick;
            if (tick == lastTick)
            {
                MaybeFinishEpisode(tick);
                return;
            }

            lastTick = tick;
            MaybeInsertQuiz(tick);
            MaybeFinishEpisode(tick);
            OnOverlaysChanged?.Invoke();
        }

        private void MaybeInsertQuiz(int tick)
        {
            if (quizResolved || manifest.Quiz == null)
            {
                return;
            }

            int insert = manifest.Quiz.InsertAt?.Tick ?? -1;
            if (insert >= 0 && tick >= insert)
            {
                session.SetPlaying(false);
                SetFace(ShowFace.Quiz);
            }
        }

        private void MaybeFinishEpisode(int tick)
        {
            int end = manifest.TickRange?.End ?? tick;
            if (tick >= end && !session.Playing && !pendingEpisodeEnd)
            {
                pendingEpisodeEnd = true;
                SetFace(ShowFace.EpisodeEnd);
            }
            else if (tick >= end && session.Playing)
            {
                // Let session stop at tail; next Update will open episode end.
                session.SetPlaying(false);
            }
        }

        private void HandleSnapshot()
        {
            if (active)
            {
                OnOverlaysChanged?.Invoke();
            }
        }

        private void HandlePlayback()
        {
            if (active)
            {
                OnOverlaysChanged?.Invoke();
            }
        }

        private void SetFace(ShowFace next)
        {
            face = next;
            hud?.ApplyFace(next);
            OnFaceChanged?.Invoke();
        }
    }

    public sealed class PlaybackHudState
    {
        public string Title;
        public string RuleLine;
        public string SegmentLabel;
        public bool Playing;
        public float Speed;
        public bool FreeLook;
        public string CaptionKind;
        public string CaptionWho;
        public string CaptionText;
        public int CaptionTick;
        public string MonologueWho;
        public string MonologueName;
        public string MonologueText;
        public int MonologueTick;
        public List<EpisodeRelationHint> RelationHints = new();
    }
}
