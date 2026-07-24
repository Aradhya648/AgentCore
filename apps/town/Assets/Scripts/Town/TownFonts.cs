using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// Runtime text font for world-space uGUI labels and the UI Toolkit panel.
    /// WebGL players have no OS font fallback, so CJK glyphs must ship inside the
    /// build: <c>Assets/Resources/Town/Fonts/NotoSansSC-Town.ttf</c> (Noto Sans SC
    /// subset, SIL OFL — regenerate via <c>apps/town/scripts/subset-cjk-font.py</c>).
    /// LegacyRuntime only covers Latin and stays as a last-resort fallback.
    /// </summary>
    public static class TownFonts
    {
        public const string ResourcePath = "Town/Fonts/NotoSansSC-Town";

        private static Font cached;
        private static bool resolved;

        public static Font UiFont
        {
            get
            {
                if (!resolved)
                {
                    resolved = true;
                    cached = Resources.Load<Font>(ResourcePath);
                    if (cached == null)
                    {
                        Debug.LogWarning(
                            $"[AgentTown] CJK font missing at Resources/{ResourcePath} — " +
                            "falling back to LegacyRuntime (Chinese text will not render on WebGL)");
                        cached = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                    }
                }

                return cached;
            }
        }
    }
}
