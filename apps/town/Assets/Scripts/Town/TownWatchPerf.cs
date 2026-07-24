using UnityEngine;
using UnityEngine.Rendering;

namespace AgentTown.Town
{
    /// <summary>
    /// Watch-path GPU/CPU clamps for Offline Demo / WebGL bird's-eye (≥30 FPS floor).
    /// Applied once at boot; does not strip town content — only quality + light policy.
    /// </summary>
    public static class TownWatchPerf
    {
        /// <summary>WebGL quality tier index in <c>QualitySettings</c> (Low).</summary>
        public const int WebGlQualityLevel = 1;

        /// <summary>
        /// Nameplates hide beyond this camera distance (metres). Bird's-eye watch sits
        /// ~20–56 m from the look target — keep plates visible across the mid framing.
        /// </summary>
        public const float NameplateHideDistance = 96f;

        /// <summary>Max concurrent world-space interaction canvases (bubbles + trade + vote).</summary>
        public const int MaxVisibleInteractionLabels = 3;

        /// <summary>URP render scale on WebGL watch path (clarity vs fill-rate).</summary>
        public const float WebGlRenderScale = 0.85f;

        private static Material webGlUnlitTemplate;
        private static readonly System.Collections.Generic.Dictionary<int, Material> UnlitCache = new();

        /// <summary>Apply once after targetFrameRate / before town spawn.</summary>
        public static void ApplyBootPolicy()
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            int levels = QualitySettings.names != null ? QualitySettings.names.Length : 0;
            int level = Mathf.Clamp(WebGlQualityLevel, 0, Mathf.Max(0, levels - 1));
            QualitySettings.SetQualityLevel(level, applyExpensiveChanges: true);
            // Hard shadows stay off — main directional light still shades Lit building meshes.
            QualitySettings.shadows = ShadowQuality.Disable;
            QualitySettings.shadowDistance = 12f;
            QualitySettings.antiAliasing = 0;
            QualitySettings.softParticles = false;
            QualitySettings.realtimeReflectionProbes = false;
            QualitySettings.anisotropicFiltering = AnisotropicFiltering.Disable;
            QualitySettings.particleRaycastBudget = 16;
            QualitySettings.vSyncCount = 0;
            QualitySettings.pixelLightCount = 0;
            QualitySettings.globalTextureMipmapLimit = 1;

            if (GraphicsSettings.currentRenderPipeline != null)
            {
                TryClampUrpAsset(GraphicsSettings.currentRenderPipeline);
            }
#endif
        }

        /// <summary>Force every realtime light to drop shadows (WebGL watch).</summary>
        public static void StripAllLightShadows()
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            Light[] lights = Object.FindObjectsByType<Light>(FindObjectsSortMode.None);
            for (int i = 0; i < lights.Length; i++)
            {
                Light light = lights[i];
                if (light != null)
                {
                    light.shadows = LightShadows.None;
                }
            }
#endif
        }

        /// <summary>
        /// After town spawn: force Unlit on ground / roads / zone slabs only.
        /// Buildings, nature, and NPCs keep Lit so sun + ambient still read as a town.
        /// </summary>
        public static void SimplifySceneForWebGl(Transform townRoot)
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            if (townRoot == null)
            {
                return;
            }

            EnsureUnlitTemplate();
            if (webGlUnlitTemplate == null)
            {
                return;
            }

            Renderer[] renderers = townRoot.GetComponentsInChildren<Renderer>(true);
            for (int i = 0; i < renderers.Length; i++)
            {
                Renderer renderer = renderers[i];
                if (renderer == null || PreferKeepLit(renderer.transform))
                {
                    continue;
                }

                ConvertRendererToUnlit(renderer);
            }
            // Intentionally no StaticBatchingUtility: TownBuildingLod toggles per-renderer
            // enabled flags; combining would fight distance LOD.
#else
            _ = townRoot;
#endif
        }

        /// <summary>
        /// Buildings + nature + NPCs stay Lit (main-light shading). Ground / roads / zones → Unlit.
        /// Nature Lit avoids green foliage melting into Unlit grass slabs.
        /// </summary>
        private static bool PreferKeepLit(Transform t)
        {
            while (t != null)
            {
                string n = t.name;
                if (n == "Buildings"
                    || n == "Nature"
                    || n == "Markers"
                    || n.IndexOf("Npc", System.StringComparison.OrdinalIgnoreCase) >= 0
                    || n.IndexOf("Resident", System.StringComparison.OrdinalIgnoreCase) >= 0
                    || n.IndexOf("Agent", System.StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return true;
                }

                t = t.parent;
            }

            return false;
        }

        private static void ConvertRendererToUnlit(Renderer renderer)
        {
            if (renderer == null || webGlUnlitTemplate == null)
            {
                return;
            }

            if (renderer is SpriteRenderer || renderer is LineRenderer || renderer is TrailRenderer)
            {
                return;
            }

            Material[] shared = renderer.sharedMaterials;
            if (shared == null || shared.Length == 0)
            {
                return;
            }

            var next = new Material[shared.Length];
            bool changed = false;
            for (int i = 0; i < shared.Length; i++)
            {
                Material src = shared[i];
                if (src == null)
                {
                    next[i] = webGlUnlitTemplate;
                    changed = true;
                    continue;
                }

                string shaderName = src.shader != null ? src.shader.name : "";
                if (shaderName.IndexOf("Unlit", System.StringComparison.OrdinalIgnoreCase) >= 0
                    || shaderName.IndexOf("UI/", System.StringComparison.OrdinalIgnoreCase) >= 0
                    || shaderName.IndexOf("Sprites/", System.StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    next[i] = src;
                    continue;
                }

                next[i] = GetOrCreateUnlit(src);
                changed = true;
            }

            if (changed)
            {
                renderer.sharedMaterials = next;
            }
        }

        private static Material GetOrCreateUnlit(Material src)
        {
            int key = src.GetInstanceID();
            if (UnlitCache.TryGetValue(key, out Material cached) && cached != null)
            {
                return cached;
            }

            var mat = new Material(webGlUnlitTemplate) { name = src.name + "_WebGlUnlit" };
            Color color = Color.white;
            if (src.HasProperty("_BaseColor"))
            {
                color = src.GetColor("_BaseColor");
            }
            else if (src.HasProperty("_Color"))
            {
                color = src.GetColor("_Color");
            }

            if (mat.HasProperty("_BaseColor"))
            {
                mat.SetColor("_BaseColor", color);
            }

            if (mat.HasProperty("_Color"))
            {
                mat.SetColor("_Color", color);
            }

            Texture tex = null;
            if (src.HasProperty("_BaseMap"))
            {
                tex = src.GetTexture("_BaseMap");
            }
            else if (src.HasProperty("_MainTex"))
            {
                tex = src.GetTexture("_MainTex");
            }

            if (tex != null)
            {
                if (mat.HasProperty("_BaseMap"))
                {
                    mat.SetTexture("_BaseMap", tex);
                }

                if (mat.HasProperty("_MainTex"))
                {
                    mat.SetTexture("_MainTex", tex);
                }
            }

            UnlitCache[key] = mat;
            return mat;
        }

        private static void EnsureUnlitTemplate()
        {
            if (webGlUnlitTemplate != null)
            {
                return;
            }

            Shader shader =
                Shader.Find("Universal Render Pipeline/Unlit")
                ?? Shader.Find("Unlit/Color")
                ?? Shader.Find("Unlit/Texture")
                ?? Shader.Find("Sprites/Default");
            if (shader == null)
            {
                return;
            }

            webGlUnlitTemplate = new Material(shader) { name = "TownWebGlUnlit" };
        }

        private static void TryClampUrpAsset(RenderPipelineAsset pipeline)
        {
            System.Type type = pipeline.GetType();
            TrySetFloat(pipeline, type, "m_ShadowDistance", 12f);
            TrySetFloat(pipeline, type, "shadowDistance", 12f);
            TrySetFloat(pipeline, type, "m_RenderScale", WebGlRenderScale);
            TrySetFloat(pipeline, type, "renderScale", WebGlRenderScale);
            TrySetBool(pipeline, type, "m_SupportsHDR", false);
            TrySetBool(pipeline, type, "supportsHDR", false);
            TrySetBool(pipeline, type, "m_MainLightShadowsSupported", false);
            TrySetBool(pipeline, type, "supportsMainLightShadows", false);
            TrySetBool(pipeline, type, "m_SoftShadowsSupported", false);
            TrySetInt(pipeline, type, "m_MSAA", 1);
            TrySetInt(pipeline, type, "m_AdditionalLightsPerObjectLimit", 0);
            TrySetInt(pipeline, type, "m_AdditionalLightsRenderingMode", 0);
        }

        private static void TrySetFloat(object target, System.Type type, string name, float value)
        {
            var prop = type.GetProperty(name);
            if (prop != null && prop.CanWrite && prop.PropertyType == typeof(float))
            {
                prop.SetValue(target, value);
                return;
            }

            var field = type.GetField(
                name,
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic);
            if (field != null && field.FieldType == typeof(float))
            {
                field.SetValue(target, value);
            }
        }

        private static void TrySetBool(object target, System.Type type, string name, bool value)
        {
            var prop = type.GetProperty(name);
            if (prop != null && prop.CanWrite && prop.PropertyType == typeof(bool))
            {
                prop.SetValue(target, value);
                return;
            }

            var field = type.GetField(
                name,
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic);
            if (field != null && field.FieldType == typeof(bool))
            {
                field.SetValue(target, value);
            }
        }

        private static void TrySetInt(object target, System.Type type, string name, int value)
        {
            var prop = type.GetProperty(name);
            if (prop != null && prop.CanWrite && prop.PropertyType == typeof(int))
            {
                prop.SetValue(target, value);
                return;
            }

            var field = type.GetField(
                name,
                System.Reflection.BindingFlags.Instance
                | System.Reflection.BindingFlags.Public
                | System.Reflection.BindingFlags.NonPublic);
            if (field != null && field.FieldType == typeof(int))
            {
                field.SetValue(target, value);
            }
        }
    }
}
