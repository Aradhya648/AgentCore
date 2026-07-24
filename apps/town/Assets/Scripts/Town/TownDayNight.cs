using AgentTown.Simulation;
using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// Drives directional sun + ambient / fog / sky from <see cref="SimulationSession.Hour"/>
    /// (0–23), porting the Desktop <c>dayNightPaletteForHour</c> keyframes into Unity.
    /// Keyframes are clamped to a watchable luminance band so Offline Demo screenshots stay
    /// readable across packs (different shoot ticks → different hours) without per-pack patches.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class TownDayNight : MonoBehaviour
    {
        /// <summary>Floor for ambient intensity after hour + modifier blend (watch readability).</summary>
        private const float AmbientFloor = 0.58f;

        /// <summary>Ceiling so noon / festival do not wash Lit buildings to white.</summary>
        private const float AmbientCeiling = 0.64f;

        /// <summary>Directional sun intensity floor — keeps building faces from collapsing to black.</summary>
        private const float SunFloor = 0.70f;

        /// <summary>Directional sun intensity ceiling — avoids overexposed midday.</summary>
        private const float SunCeiling = 0.95f;

        /// <summary>Minimum sun elevation (Y of sun position vector) so evening still has volume, not black corners.</summary>
        private const float SunElevationFloor = 16f;

        private struct Keyframe
        {
            public int Hour;
            public Color Background;
            public Color Fog;
            public float AmbientIntensity;
            public Color AmbientColor;
            public Color HemiSky;
            public Color HemiGround;
            public float HemiIntensity;
            public Color SunColor;
            public float SunIntensity;
            public Vector3 SunPosition;
            public Color SkyTint;
            public Color GroundTint;
            public float SkyExposure;
        }

        // Narrow watchable band: evening stays warm dusk (not dead black); noon is soft, not blown white.
        private static readonly Keyframe[] Keyframes =
        {
            new Keyframe
            {
                Hour = 0,
                Background = Hex("#3a4a68"), Fog = Hex("#4a5a78"),
                AmbientIntensity = 0.58f, AmbientColor = Hex("#b8c4d8"),
                HemiSky = Hex("#6a7a98"), HemiGround = Hex("#3a4458"), HemiIntensity = 0.30f,
                SunColor = Hex("#9aa8c0"), SunIntensity = 0.70f, SunPosition = new Vector3(-10f, 18f, -8f),
                SkyTint = Hex("#5a6a88"), GroundTint = Hex("#4a5868"), SkyExposure = 1.05f,
            },
            new Keyframe
            {
                Hour = 5,
                Background = Hex("#7a8aa8"), Fog = Hex("#8a9ab0"),
                AmbientIntensity = 0.60f, AmbientColor = Hex("#d8c8b8"),
                HemiSky = Hex("#b0b8c8"), HemiGround = Hex("#5a6070"), HemiIntensity = 0.32f,
                SunColor = Hex("#ffc090"), SunIntensity = 0.78f, SunPosition = new Vector3(8f, 18f, -10f),
                SkyTint = Hex("#8a9ab8"), GroundTint = Hex("#6a7868"), SkyExposure = 1.10f,
            },
            new Keyframe
            {
                Hour = 8,
                Background = Hex("#a0c8e8"), Fog = Hex("#b0d0e8"),
                AmbientIntensity = 0.62f, AmbientColor = Hex("#fff4e8"),
                HemiSky = Hex("#fff0e0"), HemiGround = Hex("#7a9fc0"), HemiIntensity = 0.34f,
                SunColor = Hex("#fff0d8"), SunIntensity = 0.88f, SunPosition = new Vector3(14f, 22f, 10f),
                SkyTint = Hex("#a8d0f0"), GroundTint = Hex("#7a9a78"), SkyExposure = 1.15f,
            },
            new Keyframe
            {
                Hour = 12,
                Background = Hex("#a8d0f0"), Fog = Hex("#b4d4f0"),
                AmbientIntensity = 0.63f, AmbientColor = Hex("#fff6ec"),
                HemiSky = Hex("#fff4e8"), HemiGround = Hex("#80a4c8"), HemiIntensity = 0.34f,
                SunColor = Hex("#fff4e0"), SunIntensity = 0.92f, SunPosition = new Vector3(0f, 28f, 8f),
                SkyTint = Hex("#b0d4f0"), GroundTint = Hex("#7a9a78"), SkyExposure = 1.15f,
            },
            new Keyframe
            {
                Hour = 17,
                Background = Hex("#e8b888"), Fog = Hex("#e0b090"),
                AmbientIntensity = 0.62f, AmbientColor = Hex("#ffe8d0"),
                HemiSky = Hex("#ffd8b0"), HemiGround = Hex("#7a8090"), HemiIntensity = 0.34f,
                SunColor = Hex("#ffb870"), SunIntensity = 0.85f, SunPosition = new Vector3(-16f, 18f, 12f),
                SkyTint = Hex("#e8b888"), GroundTint = Hex("#8a9078"), SkyExposure = 1.12f,
            },
            new Keyframe
            {
                Hour = 20,
                Background = Hex("#5a6a88"), Fog = Hex("#6a7a98"),
                AmbientIntensity = 0.58f, AmbientColor = Hex("#c8d0e0"),
                HemiSky = Hex("#7a8aa8"), HemiGround = Hex("#4a5060"), HemiIntensity = 0.30f,
                SunColor = Hex("#e0a080"), SunIntensity = 0.72f, SunPosition = new Vector3(-12f, 16f, 8f),
                SkyTint = Hex("#6a7a98"), GroundTint = Hex("#5a6858"), SkyExposure = 1.05f,
            },
        };

        private SimulationSession session;
        private Light sun;
        private Light hemi;
        private Material skyboxMaterial;
        private int lastHour = int.MinValue;
        private bool lastStorm;
        private bool lastFestival;

        public void Bind(SimulationSession target, Light directionalSun)
        {
            Unsubscribe();
            session = target;
            sun = directionalSun;
            EnsureSkybox();
            EnsureHemi();
            Subscribe();
            ApplyHour(session?.Hour ?? 12);
        }

        private void OnEnable()
        {
            session ??= SimulationSession.Instance;
            EnsureSkybox();
            Subscribe();
            ApplyHour(session.Hour);
        }

        private void OnDisable() => Unsubscribe();

        private void OnDestroy()
        {
            if (skyboxMaterial != null)
            {
                if (RenderSettings.skybox == skyboxMaterial)
                {
                    RenderSettings.skybox = null;
                }

                Destroy(skyboxMaterial);
                skyboxMaterial = null;
            }
        }

        private void LateUpdate()
        {
            if (session == null)
            {
                return;
            }

            bool storm = session.Modifiers != null && session.Modifiers.StormActive;
            bool festival = session.Modifiers != null && session.Modifiers.FestivalActive;
            if (session.Hour != lastHour || storm != lastStorm || festival != lastFestival)
            {
                ApplyHour(session.Hour);
            }
        }

        private void Subscribe()
        {
            if (session != null)
            {
                session.OnSnapshotApplied += HandleSnapshot;
            }
        }

        private void Unsubscribe()
        {
            if (session != null)
            {
                session.OnSnapshotApplied -= HandleSnapshot;
            }
        }

        private void HandleSnapshot() => ApplyHour(session.Hour);

        /// <summary>Re-apply sky dome / skybox after external camera framing (e.g. shoot landmark).</summary>
        public void RefreshSky()
        {
            ApplyHour(session != null ? session.Hour : lastHour == int.MinValue ? 12 : lastHour);
        }

        private void EnsureSkybox()
        {
            if (skyboxMaterial != null)
            {
                return;
            }

            Shader shader =
                Shader.Find("Skybox/Procedural")
                ?? Shader.Find("Skybox/Cubemap");
            if (shader == null)
            {
                Debug.LogWarning("[AgentTown] No Skybox shader — falling back to solid camera clear.");
                return;
            }

            skyboxMaterial = new Material(shader) { name = "TownDayNightSky" };
            if (skyboxMaterial.HasProperty("_AtmosphereThickness"))
            {
                // Thin atmosphere → pale, even low-poly gradient; avoids a dark anti-sun wedge.
                skyboxMaterial.SetFloat("_AtmosphereThickness", 0.5f);
            }

            if (skyboxMaterial.HasProperty("_SunDisk"))
            {
                // No sun disk — a restrained horizon→zenith gradient (0 = None).
                skyboxMaterial.SetInt("_SunDisk", 0);
            }

            RenderSettings.skybox = skyboxMaterial;
            if (Camera.main != null)
            {
                Camera.main.clearFlags = CameraClearFlags.Skybox;
            }
        }

        private void EnsureHemi()
        {
            if (hemi != null)
            {
#if UNITY_WEBGL && !UNITY_EDITOR
                hemi.enabled = false;
                hemi = null;
#else
                return;
#endif
            }

            foreach (Light existing in FindObjectsByType<Light>(FindObjectsSortMode.None))
            {
                if (existing.type == LightType.Point && existing.name == "TownHemiProxy")
                {
#if UNITY_WEBGL && !UNITY_EDITOR
                    existing.enabled = false;
#else
                    hemi = existing;
                    return;
#endif
                }
            }

            // URP has no HemisphereLight; approximate with a soft upward point + ambient.
            // WebGL: skip the point light — additional pixel lights are a common FPS cliff;
            // trilight ambient from ApplyHour carries the sky/ground tint.
#if UNITY_WEBGL && !UNITY_EDITOR
            return;
#else
            var go = new GameObject("TownHemiProxy");
            go.transform.SetParent(transform, false);
            go.transform.position = new Vector3(0f, 40f, 0f);
            hemi = go.AddComponent<Light>();
            hemi.type = LightType.Point;
            hemi.range = 200f;
            hemi.shadows = LightShadows.None;
#endif
        }

        private void ApplyHour(int hour)
        {
            lastHour = hour;
            lastStorm = session != null && session.Modifiers != null && session.Modifiers.StormActive;
            lastFestival = session != null && session.Modifiers != null && session.Modifiers.FestivalActive;

            Keyframe palette = PaletteForHour(hour);
            palette = ApplyModifierTint(palette, lastStorm, lastFestival);
            palette = ClampReadable(palette);

            // Built-in skybox renders at infinity — always behind geometry, never an object.
            if (Camera.main != null)
            {
                Camera.main.clearFlags = CameraClearFlags.Skybox;
                Camera.main.backgroundColor = palette.Fog;
            }

            ApplySkybox(palette);

            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.Linear;
            RenderSettings.fogColor = palette.Fog;
#if UNITY_WEBGL && !UNITY_EDITOR
            // WebGL: additional lights are stripped — Flat ambient is the only reliable fill.
            // Trilight ground was pulling Lit back-faces toward charcoal on evening shoots.
            float amb = Mathf.Max(palette.AmbientIntensity, AmbientFloor);
            Color fill = EnsureLuminance(
                Color.Lerp(palette.AmbientColor, palette.HemiSky, 0.35f) * amb, 0.55f);
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
            RenderSettings.ambientLight = fill;
            RenderSettings.fogStartDistance = 75f;
            RenderSettings.fogEndDistance = 160f;
#else
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Flat;
            RenderSettings.ambientLight = EnsureLuminance(
                palette.AmbientColor * Mathf.Max(palette.AmbientIntensity, AmbientFloor), 0.45f);
            RenderSettings.fogStartDistance = 100f;
            RenderSettings.fogEndDistance = 220f;
#endif

            if (sun != null)
            {
                sun.color = palette.SunColor;
                // Keep sun from overpowering ambient fill (volume without black crush / white blow).
                sun.intensity = Mathf.Min(palette.SunIntensity, SunCeiling * 0.92f);
                Vector3 sunPos = palette.SunPosition;
                if (sunPos.y < SunElevationFloor)
                {
                    sunPos.y = SunElevationFloor;
                }

                sun.transform.position = sunPos;
                if (sunPos.sqrMagnitude > 0.01f)
                {
                    sun.transform.rotation = Quaternion.LookRotation(-sunPos.normalized, Vector3.up);
                }
            }

            if (hemi != null)
            {
                hemi.color = Color.Lerp(palette.HemiSky, palette.HemiGround, 0.35f);
                hemi.intensity = palette.HemiIntensity * 8f;
            }
        }

        private void ApplySkybox(Keyframe palette)
        {
            if (skyboxMaterial == null)
            {
                return;
            }

            RenderSettings.skybox = skyboxMaterial;
            if (skyboxMaterial.HasProperty("_SkyTint"))
            {
                // Floor the tint so the anti-sun sky / horizon does not fall to a dark wedge.
                skyboxMaterial.SetColor("_SkyTint", EnsureLuminance(palette.SkyTint, 0.5f));
            }

            if (skyboxMaterial.HasProperty("_GroundColor"))
            {
                // Below-horizon hemisphere shows at the bird-cam rim beyond the ground plane —
                // keep it a soft horizon haze (never dark) so map edges are not a void.
                Color horizon = EnsureLuminance(
                    Color.Lerp(palette.Fog, palette.SkyTint, 0.4f), 0.55f);
                skyboxMaterial.SetColor("_GroundColor", horizon);
            }

            if (skyboxMaterial.HasProperty("_Exposure"))
            {
                // Lift exposure floor so corners read as bright haze, not a black gap.
                skyboxMaterial.SetFloat("_Exposure", Mathf.Max(palette.SkyExposure, 1.3f));
            }
        }

        /// <summary>
        /// Single watchability clamp for all packs — raises evening/night floors and caps noon
        /// so shoot ticks at hour 13 / 16 / 19 read in the same luminance band.
        /// </summary>
        private static Keyframe ClampReadable(Keyframe palette)
        {
            palette.AmbientIntensity = Mathf.Clamp(palette.AmbientIntensity, AmbientFloor, AmbientCeiling);
            palette.SunIntensity = Mathf.Clamp(palette.SunIntensity, SunFloor, SunCeiling);
            palette.HemiIntensity = Mathf.Max(palette.HemiIntensity, 0.22f);
            if (palette.SunPosition.y < SunElevationFloor)
            {
                palette.SunPosition = new Vector3(
                    palette.SunPosition.x,
                    SunElevationFloor,
                    palette.SunPosition.z);
            }

            return palette;
        }

        /// <summary>Scale RGB up so perceived luminance meets <paramref name="minLum"/> (0–1).</summary>
        private static Color EnsureLuminance(Color c, float minLum)
        {
            float l = 0.2126f * c.r + 0.7152f * c.g + 0.0722f * c.b;
            if (l < 0.001f)
            {
                return new Color(minLum, minLum, minLum, c.a);
            }

            if (l < minLum)
            {
                float s = minLum / l;
                return new Color(
                    Mathf.Min(c.r * s, 1.2f),
                    Mathf.Min(c.g * s, 1.2f),
                    Mathf.Min(c.b * s, 1.2f),
                    c.a);
            }

            return c;
        }

        /// <summary>Blend storm / festival into the day-night palette (Desktop <c>worldModifierPalette</c>).</summary>
        private static Keyframe ApplyModifierTint(Keyframe basePalette, bool storm, bool festival)
        {
            Keyframe next = basePalette;
            if (storm)
            {
                // Cool overcast — keep above readability floors (do not crush to night).
                next.Background = Color.Lerp(next.Background, Hex("#2a3850"), 0.40f);
                next.Fog = Color.Lerp(next.Fog, Hex("#3a4860"), 0.45f);
                next.AmbientIntensity = Mathf.Lerp(next.AmbientIntensity, 0.50f, 0.45f);
                next.AmbientColor = Color.Lerp(next.AmbientColor, Hex("#9aa8c0"), 0.4f);
                next.HemiSky = Color.Lerp(next.HemiSky, Hex("#5a6888"), 0.4f);
                next.HemiGround = Color.Lerp(next.HemiGround, Hex("#2a3040"), 0.35f);
                next.HemiIntensity = Mathf.Lerp(next.HemiIntensity, 0.22f, 0.4f);
                next.SunColor = Color.Lerp(next.SunColor, Hex("#9aa8c0"), 0.5f);
                next.SunIntensity = Mathf.Lerp(next.SunIntensity, 0.60f, 0.5f);
                next.SkyTint = Color.Lerp(next.SkyTint, Hex("#3a4860"), 0.45f);
                next.SkyExposure = Mathf.Lerp(next.SkyExposure, 0.9f, 0.4f);
            }

            if (festival)
            {
                next.Background = Color.Lerp(next.Background, Hex("#f0c898"), 0.18f);
                next.Fog = Color.Lerp(next.Fog, Hex("#e8c0a0"), 0.12f);
                next.AmbientColor = Color.Lerp(next.AmbientColor, Hex("#fff0d8"), 0.22f);
                next.HemiSky = Color.Lerp(next.HemiSky, Hex("#ffe8c8"), 0.2f);
                next.SunColor = Color.Lerp(next.SunColor, Hex("#ffe0a8"), 0.15f);
                next.SunIntensity = Mathf.Lerp(next.SunIntensity, next.SunIntensity + 0.1f, 0.25f);
                next.SkyTint = Color.Lerp(next.SkyTint, Hex("#f0c898"), 0.15f);
                next.GroundTint = Color.Lerp(next.GroundTint, Hex("#6a7058"), 0.1f);
            }

            return next;
        }

        private static Keyframe PaletteForHour(int hour)
        {
            float h = ((hour % 24) + 24) % 24;
            Keyframe from = Keyframes[Keyframes.Length - 1];
            Keyframe to = Keyframes[0];

            for (int i = 0; i < Keyframes.Length; i++)
            {
                Keyframe cur = Keyframes[i];
                Keyframe next = Keyframes[(i + 1) % Keyframes.Length];
                bool inSpan = next.Hour > cur.Hour
                    ? h >= cur.Hour && h < next.Hour
                    : h >= cur.Hour || h < next.Hour;
                if (inSpan)
                {
                    from = cur;
                    to = next;
                    break;
                }
            }

            float span = to.Hour > from.Hour ? to.Hour - from.Hour : 24 - from.Hour + to.Hour;
            float offset = h >= from.Hour ? h - from.Hour : 24 - from.Hour + h;
            float t = span > 0f ? offset / span : 0f;

            return new Keyframe
            {
                Hour = hour,
                Background = Color.Lerp(from.Background, to.Background, t),
                Fog = Color.Lerp(from.Fog, to.Fog, t),
                AmbientIntensity = Mathf.Lerp(from.AmbientIntensity, to.AmbientIntensity, t),
                AmbientColor = Color.Lerp(from.AmbientColor, to.AmbientColor, t),
                HemiSky = Color.Lerp(from.HemiSky, to.HemiSky, t),
                HemiGround = Color.Lerp(from.HemiGround, to.HemiGround, t),
                HemiIntensity = Mathf.Lerp(from.HemiIntensity, to.HemiIntensity, t),
                SunColor = Color.Lerp(from.SunColor, to.SunColor, t),
                SunIntensity = Mathf.Lerp(from.SunIntensity, to.SunIntensity, t),
                SunPosition = Vector3.Lerp(from.SunPosition, to.SunPosition, t),
                SkyTint = Color.Lerp(from.SkyTint, to.SkyTint, t),
                GroundTint = Color.Lerp(from.GroundTint, to.GroundTint, t),
                SkyExposure = Mathf.Lerp(from.SkyExposure, to.SkyExposure, t),
            };
        }

        private static Color Hex(string hex)
        {
            if (ColorUtility.TryParseHtmlString(hex, out Color color))
            {
                return color;
            }

            return Color.white;
        }
    }
}
