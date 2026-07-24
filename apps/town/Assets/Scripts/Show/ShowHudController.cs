using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.UIElements;

namespace AgentTown.Show
{
    /// <summary>Five-face programme chrome nested under TownHud (<c>show-hud</c>).</summary>
    [DisallowMultipleComponent]
    public sealed class ShowHudController : MonoBehaviour
    {
        private UIDocument document;
        private ShowModeController mode;
        private VisualElement root;
        private VisualElement faceLanding;
        private VisualElement facePlayback;
        private VisualElement faceQuiz;
        private VisualElement faceEpisodeEnd;
        private VisualElement faceSeasonEnd;
        private Label landingSeason;
        private Label landingTitle;
        private Label landingTagline;
        private Label playbackSegment;
        private Label playbackRule;
        private Label playbackCaption;
        private Label monologueWho;
        private Label monologueText;
        private Label relationBar;
        private Button playbackPause;
        private Button playbackSpeed;
        private Button playbackFree;
        private Label quizFocus;
        private Label quizQuestion;
        private Label quizHint;
        private VisualElement quizOptions;
        private Label endQuizResult;
        private Label endMonologue;
        private VisualElement endHighlights;
        private Label endTeaser;
        private bool bound;
        private float speedCycle = 1f;

        public void Bind(ShowModeController controller)
        {
            mode = controller;
            document = GetComponent<UIDocument>();
            TryBind();
            if (mode != null)
            {
                mode.OnFaceChanged += RefreshFaceContent;
                mode.OnOverlaysChanged += RefreshPlaybackOverlays;
            }
        }

        private void OnDestroy()
        {
            if (mode != null)
            {
                mode.OnFaceChanged -= RefreshFaceContent;
                mode.OnOverlaysChanged -= RefreshPlaybackOverlays;
            }
        }

        public void SetVisible(bool visible)
        {
            TryBind();
            if (root == null)
            {
                return;
            }

            if (visible)
            {
                root.RemoveFromClassList("hidden");
            }
            else
            {
                root.AddToClassList("hidden");
            }

            // WebGL: class-driven reveal is unreliable (see .npc-nameplate note in TownHud.uss);
            // inline display mirrors TownHudController.SetObservatoryChromeVisible.
            root.style.display = visible ? DisplayStyle.Flex : DisplayStyle.None;
        }

        public void ApplyFace(ShowFace face)
        {
            TryBind();
            SetFaceVisible(faceLanding, face == ShowFace.Landing);
            SetFaceVisible(facePlayback, face == ShowFace.Playback);
            SetFaceVisible(faceQuiz, face == ShowFace.Quiz);
            SetFaceVisible(faceEpisodeEnd, face == ShowFace.EpisodeEnd);
            SetFaceVisible(faceSeasonEnd, face == ShowFace.SeasonEnd);
            RefreshFaceContent();
            if (face == ShowFace.Playback)
            {
                RefreshPlaybackOverlays();
            }
        }

        private static void SetFaceVisible(VisualElement face, bool visible)
        {
            if (face == null)
            {
                return;
            }

            if (visible)
            {
                face.RemoveFromClassList("hidden");
            }
            else
            {
                face.AddToClassList("hidden");
            }

            face.style.display = visible ? DisplayStyle.Flex : DisplayStyle.None;
        }

        /// <summary>
        /// Pin face-critical styles inline. On the WebGL player, USS class styles applied
        /// via class-list mutation don't reliably repaint (same seam as .npc-nameplate) —
        /// the landing backdrop was dropped while its child labels still drew.
        /// </summary>
        private static void PinFaceStyles(VisualElement face, bool dimBackdrop)
        {
            if (face == null)
            {
                return;
            }

            face.style.position = Position.Absolute;
            face.style.left = 0;
            face.style.right = 0;
            face.style.top = 0;
            face.style.bottom = 0;
            face.style.paddingLeft = 36;
            face.style.paddingRight = 36;
            face.style.paddingTop = 28;
            face.style.paddingBottom = 28;
            if (dimBackdrop)
            {
                face.style.backgroundColor = new Color(8f / 255f, 12f / 255f, 18f / 255f, 0.82f);
                face.style.alignItems = Align.Center;
                face.style.justifyContent = Justify.Center;
            }
        }

        private void TryBind()
        {
            if (bound)
            {
                return;
            }

            document ??= GetComponent<UIDocument>();
            if (document?.rootVisualElement == null)
            {
                return;
            }

            root = document.rootVisualElement.Q("show-hud");
            if (root == null)
            {
                return;
            }

            root.style.position = Position.Absolute;
            root.style.left = 0;
            root.style.right = 0;
            root.style.top = 0;
            root.style.bottom = 0;

            faceLanding = root.Q("show-face-landing");
            facePlayback = root.Q("show-face-playback");
            faceQuiz = root.Q("show-face-quiz");
            faceEpisodeEnd = root.Q("show-face-episode-end");
            faceSeasonEnd = root.Q("show-face-season-end");
            PinFaceStyles(faceLanding, dimBackdrop: true);
            PinFaceStyles(facePlayback, dimBackdrop: false);
            PinFaceStyles(faceQuiz, dimBackdrop: true);
            PinFaceStyles(faceEpisodeEnd, dimBackdrop: true);
            PinFaceStyles(faceSeasonEnd, dimBackdrop: true);
            landingSeason = root.Q<Label>("landing-season");
            landingTitle = root.Q<Label>("landing-title");
            landingTagline = root.Q<Label>("landing-tagline");
            playbackSegment = root.Q<Label>("playback-segment");
            playbackRule = root.Q<Label>("playback-rule");
            playbackCaption = root.Q<Label>("playback-caption");
            monologueWho = root.Q<Label>("monologue-who");
            monologueText = root.Q<Label>("monologue-text");
            relationBar = root.Q<Label>("relation-bar");
            playbackPause = root.Q<Button>("playback-pause");
            playbackSpeed = root.Q<Button>("playback-speed");
            playbackFree = root.Q<Button>("playback-free");
            quizFocus = root.Q<Label>("quiz-focus");
            quizQuestion = root.Q<Label>("quiz-question");
            quizHint = root.Q<Label>("quiz-hint");
            quizOptions = root.Q("quiz-options");
            endQuizResult = root.Q<Label>("end-quiz-result");
            endMonologue = root.Q<Label>("end-monologue");
            endHighlights = root.Q("end-highlights");
            endTeaser = root.Q<Label>("end-teaser");

            WireButtons(root);
            bound = true;
        }

        private void WireButtons(VisualElement r)
        {
            r.Q<Button>("landing-continue")?.RegisterCallback<ClickEvent>(_ => mode?.StartPlaybackFromLanding());
            r.Q<Button>("landing-exit")?.RegisterCallback<ClickEvent>(_ => mode?.ExitShowMode());
            playbackPause?.RegisterCallback<ClickEvent>(_ =>
            {
                mode?.TogglePause();
                RefreshPlaybackOverlays();
            });
            playbackSpeed?.RegisterCallback<ClickEvent>(_ =>
            {
                speedCycle = speedCycle < 1.5f ? 2f : speedCycle < 3f ? 4f : 1f;
                mode?.SetSpeed(speedCycle);
                if (playbackSpeed != null)
                {
                    playbackSpeed.text = $"{speedCycle:0.#}×";
                }
            });
            playbackFree?.RegisterCallback<ClickEvent>(_ => mode?.ToggleFreeLook());
            r.Q<Button>("playback-director")?.RegisterCallback<ClickEvent>(_ => mode?.ReturnToDirector());
            r.Q<Button>("playback-exit")?.RegisterCallback<ClickEvent>(_ => mode?.ExitShowMode());
            r.Q<Button>("monologue-cycle")?.RegisterCallback<ClickEvent>(_ => mode?.CycleMonologueFocus());
            r.Q<Button>("end-season")?.RegisterCallback<ClickEvent>(_ => mode?.ShowSeasonEndPlaceholder());
            r.Q<Button>("end-exit")?.RegisterCallback<ClickEvent>(_ => mode?.ExitShowMode());
            r.Q<Button>("season-back")?.RegisterCallback<ClickEvent>(_ => mode?.ReturnToEpisodeEnd());
        }

        private void RefreshFaceContent()
        {
            if (!bound || mode?.Manifest == null)
            {
                return;
            }

            EpisodeManifest m = mode.Manifest;
            if (landingSeason != null)
            {
                landingSeason.text = $"{m.Season} · 第 {m.EpisodeNo} 期";
            }

            if (landingTitle != null)
            {
                landingTitle.text = m.Title ?? "";
            }

            if (landingTagline != null)
            {
                landingTagline.text = m.Tagline ?? "";
            }

            if (mode.Face == ShowFace.Quiz)
            {
                RefreshQuiz();
            }

            if (mode.Face == ShowFace.EpisodeEnd)
            {
                RefreshEpisodeEnd();
            }
        }

        private void RefreshQuiz()
        {
            EpisodeQuiz quiz = mode?.Manifest?.Quiz;
            if (quiz == null)
            {
                return;
            }

            if (quizFocus != null)
            {
                quizFocus.text = $"今晚 · 焦点：{ShowCast.DisplayName(quiz.Focus)}";
            }

            if (quizQuestion != null)
            {
                quizQuestion.text = quiz.Question ?? "";
            }

            if (quizHint != null)
            {
                quizHint.text = quiz.Hint ?? "";
            }

            if (quizOptions == null)
            {
                return;
            }

            quizOptions.Clear();
            foreach (string option in quiz.Options ?? new List<string>())
            {
                string captured = option;
                var btn = new Button(() => mode.SubmitQuizPick(captured))
                {
                    text = ShowCast.DisplayName(captured),
                    name = $"quiz-opt-{captured}",
                };
                btn.AddToClassList("quiz-option");
                quizOptions.Add(btn);
            }
        }

        private void RefreshEpisodeEnd()
        {
            EpisodeManifest m = mode.Manifest;
            if (endQuizResult != null)
            {
                if (string.IsNullOrEmpty(mode.QuizPick))
                {
                    endQuizResult.text = "本集未竞猜";
                }
                else
                {
                    endQuizResult.text = mode.QuizCorrect
                        ? $"竞猜正确 · 你选了{ShowCast.DisplayName(mode.QuizPick)}"
                        : $"竞猜未中 · 你选了{ShowCast.DisplayName(mode.QuizPick)}，答案是{ShowCast.DisplayName(m.Quiz?.Answer)}";
                }
            }

            if (endMonologue != null)
            {
                EpisodeOverlayView mono = EpisodeManifestLoader.FindOverlayById(
                    m, m.Reveal?.AnswerOverlayId);
                endMonologue.text = mono != null
                    ? $"{ShowCast.DisplayName(mono.Who)}：「{mono.Text}」"
                    : "";
            }

            if (endHighlights != null)
            {
                endHighlights.Clear();
                foreach (EpisodeHighlight h in m.Highlights ?? new List<EpisodeHighlight>())
                {
                    EpisodeHighlight captured = h;
                    var btn = new Button(() => mode.JumpToHighlight(captured))
                    {
                        text = $"{h.Title}\n「{h.Quote}」— {ShowCast.DisplayName(h.By)}",
                    };
                    btn.AddToClassList("highlight-btn");
                    endHighlights.Add(btn);
                }
            }

            if (endTeaser != null && m.NextTeaser != null)
            {
                endTeaser.text = $"{m.NextTeaser.Title}\n{m.NextTeaser.Hook}";
            }
        }

        private void RefreshPlaybackOverlays()
        {
            if (!bound || mode == null || mode.Face != ShowFace.Playback)
            {
                return;
            }

            PlaybackHudState state = mode.CapturePlaybackHud();
            if (playbackSegment != null)
            {
                playbackSegment.text = string.IsNullOrEmpty(state.SegmentLabel)
                    ? state.Title
                    : state.SegmentLabel;
            }

            if (playbackRule != null)
            {
                playbackRule.text = state.RuleLine ?? "";
            }

            if (playbackCaption != null)
            {
                string who = string.IsNullOrEmpty(state.CaptionWho)
                    ? ""
                    : $"{ShowCast.DisplayName(state.CaptionWho)}：";
                playbackCaption.text = string.IsNullOrEmpty(state.CaptionText)
                    ? ""
                    : who + state.CaptionText;
            }

            if (monologueWho != null)
            {
                monologueWho.text = string.IsNullOrEmpty(state.MonologueName)
                    ? ""
                    : state.MonologueName;
            }

            if (monologueText != null)
            {
                monologueText.text = string.IsNullOrEmpty(state.MonologueText)
                    ? ""
                    : $"「{state.MonologueText}」";
            }

            if (relationBar != null)
            {
                relationBar.text = FormatRelations(state.RelationHints);
            }

            if (playbackPause != null)
            {
                playbackPause.text = state.Playing ? "暂停" : "播放";
            }

            if (playbackFree != null)
            {
                playbackFree.text = state.FreeLook ? "自由中…" : "自由机位";
            }

            if (playbackSpeed != null)
            {
                playbackSpeed.text = $"{state.Speed:0.#}×";
                speedCycle = state.Speed;
            }
        }

        private static string FormatRelations(List<EpisodeRelationHint> hints)
        {
            if (hints == null || hints.Count == 0)
            {
                return "";
            }

            var sb = new StringBuilder();
            for (int i = 0; i < hints.Count; i++)
            {
                EpisodeRelationHint h = hints[i];
                if (i > 0)
                {
                    sb.Append("  ·  ");
                }

                string to = h.To == "all" ? "全场" : ShowCast.DisplayName(h.To);
                sb.Append($"{ShowCast.DisplayName(h.From)}→{to} {h.Label}");
            }

            return sb.ToString();
        }
    }
}
