using AgentTown.Town;
using NUnit.Framework;
using UnityEngine;

namespace AgentTown.Tests
{
    public sealed class TownFontsTests
    {
        /// <summary>
        /// WebGL has no OS font fallback: the bundled Noto Sans SC subset is the only
        /// source of CJK glyphs for world labels, nameplates and the HUD. Guard the
        /// asset so build-size trimming cannot silently regress Chinese text again.
        /// </summary>
        [Test]
        public void CjkSubsetFont_IsBundledInResources()
        {
            Font font = Resources.Load<Font>(TownFonts.ResourcePath);
            Assert.IsNotNull(
                font,
                $"missing Resources/{TownFonts.ResourcePath}.ttf — regenerate via " +
                "apps/town/scripts/subset-cjk-font.py (Noto Sans SC, OFL)");
        }

        [Test]
        public void UiFont_ResolvesWithoutThrowing()
        {
            Assert.IsNotNull(TownFonts.UiFont);
        }
    }
}
