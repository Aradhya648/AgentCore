using System.Collections.Generic;
using AgentTown.Simulation;
using UnityEngine;
using UnityEngine.UI;

namespace AgentTown.Town
{
    /// <summary>
    /// 3D overlays for active interactions — conversation bubbles, trade icons, vote bar.
    /// Semantic port of Desktop <c>InteractionOverlays.tsx</c>.
    /// Anchors prefer live <see cref="TownNpc"/> transforms; Offline cues fade by playhead age.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class TownInteractionOverlays : MonoBehaviour
    {
        private const float BubbleY = 2.65f;
        private const float TradeY = 2.4f;
        private const float VoteY = 6.5f;
        /// <summary>World-space UI scale — readable from bird distance without a translucent wall.</summary>
#if UNITY_WEBGL && !UNITY_EDITOR
        private const float UiScale = 0.02f;
        private const int BubbleFontSize = 16;
#else
        private const float UiScale = 0.024f;
        private const int BubbleFontSize = 18;
#endif
        private const float MinVisibleAlpha = 0.04f;

        private SimulationSession session;
        private TownNpcManager npcManager;
        private Transform container;
        private readonly List<OverlayEntry> spawned = new();
        private float nextFollowAt;

        private sealed class OverlayEntry
        {
            public GameObject Root;
            public string FollowAgentId;
            public float YOffset;
            public string FollowAgentB;
            public float LineYOffset;
            public LineRenderer Line;
            public Image Background;
            public Text Label;
            public Color BaseBg;
            public Color BaseText = Color.white;
            public Color BaseLine;
            public ActiveInteraction Source;
            public bool IsLine;
        }

        public void Bind(SimulationSession target)
        {
            Unsubscribe();
            session = target;
            npcManager = FindFirstObjectByType<TownNpcManager>();
            Subscribe();
            Rebuild();
        }

        private void OnEnable()
        {
            session ??= SimulationSession.Instance;
            npcManager ??= FindFirstObjectByType<TownNpcManager>();
            Subscribe();
            Rebuild();
        }

        private void OnDisable() => Unsubscribe();

        private void LateUpdate()
        {
            if (spawned.Count == 0)
            {
                return;
            }

            // Bird watch: follow/billboard does not need 60 Hz — cut Canvas churn on WebGL.
            if (Time.unscaledTime < nextFollowAt)
            {
                return;
            }

            nextFollowAt = Time.unscaledTime + 0.1f;

            for (int i = 0; i < spawned.Count; i++)
            {
                OverlayEntry entry = spawned[i];
                if (entry?.Root == null)
                {
                    continue;
                }

                float alpha = ResolveAlpha(entry.Source);
                if (alpha < MinVisibleAlpha)
                {
                    entry.Root.SetActive(false);
                    continue;
                }

                entry.Root.SetActive(true);
                ApplyAlpha(entry, alpha);

                if (entry.IsLine)
                {
                    UpdateLine(entry);
                }
                else if (!string.IsNullOrEmpty(entry.FollowAgentB)
                         && !string.IsNullOrEmpty(entry.FollowAgentId)
                         && TryMidpoint(entry.FollowAgentId, entry.FollowAgentB, entry.YOffset, out Vector3 mid))
                {
                    entry.Root.transform.position = mid;
                }
                else if (!string.IsNullOrEmpty(entry.FollowAgentId)
                         && TryAgentPos(entry.FollowAgentId, out Vector3 pos))
                {
                    pos.y += entry.YOffset;
                    entry.Root.transform.position = pos;
                }
            }
        }

        private void Subscribe()
        {
            if (session == null)
            {
                return;
            }

            session.OnInteractionsChanged += Rebuild;
            session.OnSnapshotApplied += Rebuild;
            session.OnPlaybackChanged += Rebuild;
        }

        private void Unsubscribe()
        {
            if (session == null)
            {
                return;
            }

            session.OnInteractionsChanged -= Rebuild;
            session.OnSnapshotApplied -= Rebuild;
            session.OnPlaybackChanged -= Rebuild;
        }

        private void Rebuild()
        {
            ClearSpawned();
            if (session == null)
            {
                return;
            }

            EnsureContainer();
            int labelBudget = TownWatchPerf.MaxVisibleInteractionLabels;
            foreach (KeyValuePair<string, ActiveInteraction> pair in session.ActiveInteractions)
            {
                ActiveInteraction ix = pair.Value;
                if (ix == null)
                {
                    continue;
                }

                if (ResolveAlpha(ix) < MinVisibleAlpha)
                {
                    continue;
                }

                switch (ix.Kind)
                {
                    case "conversation":
                        if (labelBudget <= 0)
                        {
                            break;
                        }

                        SpawnConversation(ix, ref labelBudget);
                        break;
                    case "trade":
                        if (labelBudget <= 0)
                        {
                            break;
                        }

                        SpawnTrade(ix, ref labelBudget);
                        break;
                    case "vote":
                        if (labelBudget <= 0)
                        {
                            break;
                        }

                        SpawnVote(ix, ref labelBudget);
                        break;
                }
            }
        }

        private float ResolveAlpha(ActiveInteraction ix)
        {
            if (ix == null || session == null)
            {
                return 0f;
            }

            return InteractionModel.OverlayAlpha(
                ix,
                session.DisplayTick,
                session.IsOffline,
                session.PlaybackSpeed);
        }

        private void SpawnConversation(ActiveInteraction ix, ref int labelBudget)
        {
            if (string.IsNullOrEmpty(ix.TargetId))
            {
                return;
            }

            string initiatorLine = InteractionModel.LinesForAgent(ix.Transcript, ix.InitiatorId)
                ?? InteractionModel.LastLineForAgent(ix.Transcript, ix.InitiatorId)
                ?? ix.Summary;
            string targetLine = InteractionModel.LinesForAgent(ix.Transcript, ix.TargetId)
                ?? InteractionModel.LastLineForAgent(ix.Transcript, ix.TargetId)
                ?? ix.Summary;

            if (labelBudget > 0)
            {
                SpawnBubble(ix, ix.InitiatorId, initiatorLine, BubbleY);
                labelBudget--;
            }

            if (labelBudget > 0)
            {
                SpawnBubble(ix, ix.TargetId, targetLine, BubbleY);
                labelBudget--;
            }

            SpawnConnection(ix, ix.InitiatorId, ix.TargetId);
        }

        private void SpawnTrade(ActiveInteraction ix, ref int labelBudget)
        {
            if (string.IsNullOrEmpty(ix.TargetId) || labelBudget <= 0)
            {
                return;
            }

            if (!TryMidpoint(ix.InitiatorId, ix.TargetId, TradeY, out Vector3 mid))
            {
                return;
            }

            bool ok = InteractionModel.Succeeded(ix.Status);
            // Text prefix (not emoji): the bundled CJK subset has no astral glyphs.
            string label = $"交易 {InteractionModel.TradeBriefLabel(ix)}\n{(ok ? "成交" : "未成交")}";
            Color bg = ok
                ? new Color(0.2f, 0.75f, 0.4f, 0.92f)
                : new Color(0.85f, 0.3f, 0.3f, 0.92f);
            // Midpoint labels re-anchor each LateUpdate via both agents.
            OverlayEntry entry = SpawnWorldLabel(mid, label, bg, ix);
            entry.FollowAgentId = ix.InitiatorId;
            entry.FollowAgentB = ix.TargetId;
            entry.YOffset = TradeY;
            labelBudget--;
        }

        private void SpawnVote(ActiveInteraction ix, ref int labelBudget)
        {
            if (labelBudget <= 0)
            {
                return;
            }

            InteractionModel.VoteGovernanceDetails(
                ix.StateChanges, out string motion, out string outcome, out int yes, out int no, out int abstain);

            string title = string.IsNullOrEmpty(motion)
                ? InteractionModel.Truncate(ix.Summary, 36)
                : motion;
            string body = string.IsNullOrEmpty(outcome)
                ? $"镇政厅投票\n{title}\n支持 {yes} · 反对 {no} · 弃权 {abstain}\n计票中…"
                : $"镇政厅投票\n{title}\n支持 {yes} · 反对 {no} · 弃权 {abstain}\n结果：{outcome}";

            Vector3 pos = ResolveRegion("镇政厅") + new Vector3(0f, VoteY, 0f);
            SpawnWorldLabel(pos, body, new Color(0.12f, 0.14f, 0.2f, 0.92f), ix);
            labelBudget--;
        }

        private void SpawnBubble(ActiveInteraction ix, string agentId, string text, float yOffset)
        {
            if (!TryAgentPos(agentId, out Vector3 pos))
            {
                return;
            }

            pos.y += yOffset;
            OverlayEntry entry = SpawnWorldLabel(
                pos,
                // Multi-line agent bubbles already truncate per line in LinesForAgent;
                // allow a longer total so 2–3 lines remain readable.
                InteractionModel.Truncate(text, 120),
                // Opaque enough to read; not a half-transparent wall at bird distance.
                new Color(0.12f, 0.16f, 0.24f, 0.96f),
                ix);
            entry.FollowAgentId = agentId;
            entry.YOffset = yOffset;
        }

        private void SpawnConnection(ActiveInteraction ix, string agentA, string agentB)
        {
            if (!TryAgentPos(agentA, out Vector3 a) || !TryAgentPos(agentB, out Vector3 b))
            {
                return;
            }

            a.y += 2.2f;
            b.y += 2.2f;
            var go = new GameObject("IxLine");
            go.transform.SetParent(container, false);
            LineRenderer line = go.AddComponent<LineRenderer>();
            line.positionCount = 2;
            line.SetPosition(0, a);
            line.SetPosition(1, b);
            line.startWidth = 0.06f;
            line.endWidth = 0.06f;
            line.material = new Material(
                Shader.Find("Sprites/Default")
                ?? Shader.Find("Unlit/Color")
                ?? Shader.Find("UI/Default")
                ?? Shader.Find("Standard"));
            Color lineColor = new Color(0.49f, 0.78f, 0.91f, 0.9f);
            line.startColor = lineColor;
            line.endColor = lineColor;
            spawned.Add(new OverlayEntry
            {
                Root = go,
                FollowAgentId = agentA,
                FollowAgentB = agentB,
                LineYOffset = 2.2f,
                Line = line,
                BaseLine = lineColor,
                Source = ix,
                IsLine = true,
            });
        }

        private OverlayEntry SpawnWorldLabel(Vector3 worldPos, string text, Color bg, ActiveInteraction source)
        {
            var go = new GameObject("IxLabel");
            go.transform.SetParent(container, false);
            go.transform.position = worldPos;
            go.transform.localScale = Vector3.one * UiScale;

            Canvas canvas = go.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = Camera.main;
            var rt = go.GetComponent<RectTransform>();
            // Height scales with line count so multi-line Live/Offline bubbles are readable.
#if UNITY_WEBGL && !UNITY_EDITOR
            rt.sizeDelta = new Vector2(240f, InteractionModel.BubbleHeightPx(text) * 0.9f);
#else
            rt.sizeDelta = new Vector2(280f, InteractionModel.BubbleHeightPx(text));
#endif

            var bgGo = new GameObject("Bg");
            bgGo.transform.SetParent(go.transform, false);
            Image image = bgGo.AddComponent<Image>();
            image.color = bg;
            var bgRt = bgGo.GetComponent<RectTransform>();
            bgRt.anchorMin = Vector2.zero;
            bgRt.anchorMax = Vector2.one;
            bgRt.offsetMin = Vector2.zero;
            bgRt.offsetMax = Vector2.zero;

            var textGo = new GameObject("Text");
            textGo.transform.SetParent(go.transform, false);
            Text label = textGo.AddComponent<Text>();
            label.font = TownFonts.UiFont;
            label.fontSize = BubbleFontSize;
            label.alignment = TextAnchor.MiddleCenter;
            label.color = Color.white;
            label.horizontalOverflow = HorizontalWrapMode.Wrap;
            label.verticalOverflow = VerticalWrapMode.Overflow;
            label.raycastTarget = false;
            label.text = text;
            var textRt = textGo.GetComponent<RectTransform>();
            textRt.anchorMin = Vector2.zero;
            textRt.anchorMax = Vector2.one;
            textRt.offsetMin = new Vector2(8f, 6f);
            textRt.offsetMax = new Vector2(-8f, -6f);

            go.AddComponent<BillboardFacing>();
            var entry = new OverlayEntry
            {
                Root = go,
                Background = image,
                Label = label,
                BaseBg = bg,
                BaseText = Color.white,
                Source = source,
            };
            spawned.Add(entry);
            return entry;
        }

        private void UpdateLine(OverlayEntry entry)
        {
            if (entry.Line == null)
            {
                return;
            }

            if (!TryAgentPos(entry.FollowAgentId, out Vector3 a)
                || !TryAgentPos(entry.FollowAgentB, out Vector3 b))
            {
                return;
            }

            a.y += entry.LineYOffset;
            b.y += entry.LineYOffset;
            entry.Line.SetPosition(0, a);
            entry.Line.SetPosition(1, b);
        }

        private static void ApplyAlpha(OverlayEntry entry, float alpha)
        {
            if (entry.IsLine && entry.Line != null)
            {
                Color c = entry.BaseLine;
                c.a = entry.BaseLine.a * alpha;
                entry.Line.startColor = c;
                entry.Line.endColor = c;
                return;
            }

            if (entry.Background != null)
            {
                Color bg = entry.BaseBg;
                bg.a = entry.BaseBg.a * alpha;
                entry.Background.color = bg;
            }

            if (entry.Label != null)
            {
                Color text = entry.BaseText;
                text.a = entry.BaseText.a * alpha;
                entry.Label.color = text;
            }
        }

        private bool TryMidpoint(string a, string b, float yOffset, out Vector3 mid)
        {
            mid = default;
            if (!TryAgentPos(a, out Vector3 pa) || !TryAgentPos(b, out Vector3 pb))
            {
                return false;
            }

            mid = (pa + pb) * 0.5f;
            mid.y += yOffset;
            return true;
        }

        private bool TryAgentPos(string agentId, out Vector3 pos)
        {
            pos = default;
            if (string.IsNullOrEmpty(agentId))
            {
                return false;
            }

            npcManager ??= FindFirstObjectByType<TownNpcManager>();
            if (npcManager != null && npcManager.TryGetLiveWorldPosition(agentId, out pos))
            {
                return true;
            }

            if (session != null
                && session.AgentUnityPositions.TryGetValue(agentId, out Vector3 wirePos))
            {
                pos = wirePos + TownPersonas.UnitySpawnOffset(agentId);
                return true;
            }

            return false;
        }

        private Vector3 ResolveRegion(string regionId)
        {
            TownBuilder builder = FindFirstObjectByType<TownBuilder>();
            if (builder != null && builder.RegionAnchors.TryGetValue(regionId, out Vector3 anchor))
            {
                return anchor;
            }

            return WireCoordinateTransform.ToUnity(-12, 0, -10);
        }

        private void EnsureContainer()
        {
            if (container == null)
            {
                container = new GameObject("InteractionOverlays").transform;
                container.SetParent(transform, false);
            }
        }

        private void ClearSpawned()
        {
            for (int i = 0; i < spawned.Count; i++)
            {
                GameObject go = spawned[i]?.Root;
                if (go != null)
                {
                    if (Application.isPlaying) Object.Destroy(go);
                    else Object.DestroyImmediate(go);
                }
            }

            spawned.Clear();
        }

        /// <summary>Billboard helper for world-space labels.</summary>
        private sealed class BillboardFacing : MonoBehaviour
        {
            private float nextAt;

            private void LateUpdate()
            {
                if (Time.unscaledTime < nextAt)
                {
                    return;
                }

                nextAt = Time.unscaledTime + 0.12f;
                Camera cam = Camera.main;
                if (cam == null)
                {
                    return;
                }

                transform.rotation = Quaternion.LookRotation(
                    transform.position - cam.transform.position, Vector3.up);
            }
        }
    }
}
