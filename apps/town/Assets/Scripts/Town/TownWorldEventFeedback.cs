using System.Collections.Generic;
using AgentTown.Simulation;
using UnityEngine;
using UnityEngine.UI;

namespace AgentTown.Town
{
    /// <summary>
    /// In-scene world-event feedback: center short banner + soft region highlight tint.
    /// Reads <see cref="SimulationSession.ActiveEvents"/> / modifiers — no Events Tab required.
    /// WebGL uses a lightweight title-only banner (small canvas, short dwell) to avoid fill-rate cliffs.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class TownWorldEventFeedback : MonoBehaviour
    {
        private const float BannerUiScale = 0.022f;
        private const float BannerUiScaleWebGl = 0.014f;
        private const float BannerY = 9.5f;
        private const float HighlightBoost = 0.22f;
        private const float WebGlBannerDwellSeconds = 3.5f;

        private SimulationSession session;
        private TownRegionHeatmap heatmap;
        private Transform bannerRoot;
        private Image bannerBg;
        private Text bannerTitle;
        private Text bannerSubtitle;
        private string lastBannerKey = "";
        private float nextBannerFollowAt;
        private float bannerHideAt;

        public void Bind(SimulationSession target)
        {
            Unsubscribe();
            session = target;
            heatmap ??= FindFirstObjectByType<TownRegionHeatmap>();
            Subscribe();
            Refresh();
        }

        private void OnEnable()
        {
            session ??= SimulationSession.Instance;
            heatmap ??= FindFirstObjectByType<TownRegionHeatmap>();
            Subscribe();
            Refresh();
        }

        private void OnDisable() => Unsubscribe();

        private void Subscribe()
        {
            if (session == null)
            {
                return;
            }

            session.OnSnapshotApplied += Refresh;
            session.OnPlaybackChanged += Refresh;
        }

        private void Unsubscribe()
        {
            if (session == null)
            {
                return;
            }

            session.OnSnapshotApplied -= Refresh;
            session.OnPlaybackChanged -= Refresh;
        }

        private void LateUpdate()
        {
            if (bannerRoot == null || !bannerRoot.gameObject.activeSelf)
            {
                return;
            }

#if UNITY_WEBGL && !UNITY_EDITOR
            if (bannerHideAt > 0f && Time.unscaledTime >= bannerHideAt)
            {
                HideBanner();
                return;
            }
#endif

            if (Time.unscaledTime < nextBannerFollowAt)
            {
                return;
            }

#if UNITY_WEBGL && !UNITY_EDITOR
            nextBannerFollowAt = Time.unscaledTime + 0.28f;
#else
            nextBannerFollowAt = Time.unscaledTime + 0.12f;
#endif

            Camera cam = Camera.main;
            if (cam == null)
            {
                return;
            }

            // Keep banner centered in front of the camera, slightly above horizon.
            Vector3 forward = cam.transform.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.001f)
            {
                forward = Vector3.forward;
            }

            forward.Normalize();
            Vector3 pos = cam.transform.position + forward * 18f + Vector3.up * (BannerY - cam.transform.position.y * 0.15f);
            bannerRoot.position = pos;
            bannerRoot.rotation = Quaternion.LookRotation(bannerRoot.position - cam.transform.position, Vector3.up);
        }

        private void Refresh()
        {
            if (session == null)
            {
                HideBanner();
                heatmap?.ClearEventHighlights();
                return;
            }

            bool hasBanner = WorldEventFeedback.TryResolveBanner(
                session.ActiveEvents, session.Modifiers, out WorldEventFeedback.Banner banner);
            if (!hasBanner)
            {
                HideBanner();
            }
            else
            {
                ShowBanner(banner);
            }

            IReadOnlyList<string> regions = WorldEventFeedback.HighlightRegions(
                session.ActiveEvents, session.Modifiers);
            heatmap ??= FindFirstObjectByType<TownRegionHeatmap>();
            float boost = HighlightBoost;
#if UNITY_WEBGL && !UNITY_EDITOR
            boost *= 0.4f;
#endif
            heatmap?.SetEventHighlights(regions, boost);
        }

        private void ShowBanner(WorldEventFeedback.Banner banner)
        {
            EnsureBanner();
            string subtitle = banner.Subtitle ?? "";
#if UNITY_WEBGL && !UNITY_EDITOR
            // Title-only on WebGL — less canvas height / overdraw; HUD chips still carry detail.
            subtitle = "";
#endif
            string key = banner.ToneId + "|" + banner.Title + "|" + subtitle;
            if (key != lastBannerKey)
            {
                lastBannerKey = key;
                bannerTitle.text = banner.Title;
                bool hasSub = !string.IsNullOrEmpty(subtitle);
                bannerSubtitle.text = subtitle;
                bannerSubtitle.gameObject.SetActive(hasSub);
                bannerBg.color = ToneColor(banner.ToneId);
                var rt = bannerRoot.GetComponent<RectTransform>();
#if UNITY_WEBGL && !UNITY_EDITOR
                rt.sizeDelta = new Vector2(280f, 48f);
#else
                // Tall enough for a title + wrapped narrative subtitle (进货/价格等).
                rt.sizeDelta = new Vector2(440f, hasSub ? 118f : 64f);
#endif
            }

            bannerRoot.gameObject.SetActive(true);
#if UNITY_WEBGL && !UNITY_EDITOR
            bannerHideAt = Time.unscaledTime + WebGlBannerDwellSeconds;
#endif
        }

        private void HideBanner()
        {
            lastBannerKey = "";
            bannerHideAt = 0f;
            if (bannerRoot != null)
            {
                bannerRoot.gameObject.SetActive(false);
            }
        }

        private void EnsureBanner()
        {
            if (bannerRoot != null)
            {
                return;
            }

            var go = new GameObject("WorldEventBanner");
            go.transform.SetParent(transform, false);
#if UNITY_WEBGL && !UNITY_EDITOR
            go.transform.localScale = Vector3.one * BannerUiScaleWebGl;
#else
            go.transform.localScale = Vector3.one * BannerUiScale;
#endif

            Canvas canvas = go.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = Camera.main;
            var rt = go.GetComponent<RectTransform>();
#if UNITY_WEBGL && !UNITY_EDITOR
            rt.sizeDelta = new Vector2(280f, 48f);
#else
            rt.sizeDelta = new Vector2(440f, 64f);
#endif

            var bgGo = new GameObject("Bg");
            bgGo.transform.SetParent(go.transform, false);
            bannerBg = bgGo.AddComponent<Image>();
            bannerBg.color = ToneColor("neutral");
            var bgRt = bgGo.GetComponent<RectTransform>();
            bgRt.anchorMin = Vector2.zero;
            bgRt.anchorMax = Vector2.one;
            bgRt.offsetMin = Vector2.zero;
            bgRt.offsetMax = Vector2.zero;

            Font font = TownFonts.UiFont;

            var titleGo = new GameObject("Title");
            titleGo.transform.SetParent(go.transform, false);
            bannerTitle = titleGo.AddComponent<Text>();
            bannerTitle.font = font;
#if UNITY_WEBGL && !UNITY_EDITOR
            bannerTitle.fontSize = 22;
#else
            bannerTitle.fontSize = 26;
#endif
            bannerTitle.fontStyle = FontStyle.Bold;
            bannerTitle.alignment = TextAnchor.MiddleCenter;
            bannerTitle.color = Color.white;
            bannerTitle.horizontalOverflow = HorizontalWrapMode.Wrap;
            bannerTitle.verticalOverflow = VerticalWrapMode.Truncate;
            bannerTitle.raycastTarget = false;
            var titleRt = titleGo.GetComponent<RectTransform>();
#if UNITY_WEBGL && !UNITY_EDITOR
            titleRt.anchorMin = Vector2.zero;
            titleRt.anchorMax = Vector2.one;
            titleRt.offsetMin = new Vector2(12f, 6f);
            titleRt.offsetMax = new Vector2(-12f, -6f);
#else
            titleRt.anchorMin = new Vector2(0f, 0.55f);
            titleRt.anchorMax = Vector2.one;
            titleRt.offsetMin = new Vector2(16f, 0f);
            titleRt.offsetMax = new Vector2(-16f, -10f);
#endif

            var subGo = new GameObject("Subtitle");
            subGo.transform.SetParent(go.transform, false);
            bannerSubtitle = subGo.AddComponent<Text>();
            bannerSubtitle.font = font;
            bannerSubtitle.fontSize = 16;
            bannerSubtitle.fontStyle = FontStyle.Normal;
            bannerSubtitle.alignment = TextAnchor.UpperCenter;
            bannerSubtitle.color = new Color(0.92f, 0.94f, 0.98f, 0.95f);
            bannerSubtitle.horizontalOverflow = HorizontalWrapMode.Wrap;
            bannerSubtitle.verticalOverflow = VerticalWrapMode.Truncate;
            bannerSubtitle.raycastTarget = false;
            var subRt = subGo.GetComponent<RectTransform>();
            subRt.anchorMin = Vector2.zero;
            subRt.anchorMax = new Vector2(1f, 0.58f);
            subRt.offsetMin = new Vector2(18f, 10f);
            subRt.offsetMax = new Vector2(-18f, -2f);
#if UNITY_WEBGL && !UNITY_EDITOR
            subGo.SetActive(false);
#endif

            bannerRoot = go.transform;
            go.SetActive(false);
        }

        private static Color ToneColor(string toneId) => toneId switch
        {
            "storm" => new Color(0.22f, 0.28f, 0.42f, 0.88f),
            "festival" => new Color(0.55f, 0.28f, 0.42f, 0.88f),
            "price" => new Color(0.55f, 0.38f, 0.12f, 0.88f),
            "announce" => new Color(0.18f, 0.32f, 0.48f, 0.88f),
            _ => new Color(0.14f, 0.16f, 0.22f, 0.88f),
        };
    }
}
