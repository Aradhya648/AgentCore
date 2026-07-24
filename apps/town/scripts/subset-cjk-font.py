# Subset Noto Sans SC for AgentTown runtime text (uGUI world labels + UI Toolkit HUD).
#
# WebGL has no OS font fallback, so CJK must ship inside the build — but the full
# Noto Sans SC is ~17 MB. This script pins the variable font to Regular (wght=400)
# and subsets it to:
#   * every non-ASCII char found in town runtime text sources (code strings, UXML,
#     StreamingAssets fixtures, story-pack SoT),
#   * GB2312 level-1 (3755 common hanzi) as a buffer for live/scripted backend text,
#   * ASCII + CJK punctuation + arrows/geometric symbols used by the HUD.
#
# Usage (repo root; needs the variable TTF downloaded first):
#   uv run --no-project --with fonttools python apps/town/scripts/subset-cjk-font.py ^
#       <NotoSansSC[wght].ttf> apps/town/Assets/Resources/Town/Fonts/NotoSansSC-Town.ttf
#
# Font: Noto Sans SC (SIL OFL 1.1) — keep OFL.txt next to the output asset.

import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

REPO = Path(__file__).resolve().parents[3]

SOURCE_GLOBS = [
    ("apps/town/Assets/Scripts", "**/*.cs"),
    ("apps/town/Assets/UI", "**/*.uxml"),
    ("apps/town/Assets/UI", "**/*.uss"),
    ("apps/town/Assets/StreamingAssets", "**/*.json"),
    ("packages/town-story-packs", "**/*.json"),
]

# HUD symbols + CJK punctuation that may not appear in scanned sources yet.
SYMBOL_BUFFER = (
    "×·—–…‘’“”「」『』（）《》〈〉【】、。，；：？！～"
    "→←↑↓▶◀►◄●○◆◇■□▲△▼▽★☆℃％¥"
    "0123456789"
)


def collect_chars() -> tuple[set[str], set[str]]:
    chars: set[str] = set()
    astral: set[str] = set()
    for base, pattern in SOURCE_GLOBS:
        root = REPO / base
        if not root.exists():
            print(f"warn: source root missing: {root}")
            continue
        for path in root.glob(pattern):
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for ch in text:
                cp = ord(ch)
                if cp < 0x20:
                    continue
                if cp > 0xFFFF:
                    astral.add(ch)
                elif cp >= 0x80:
                    chars.add(ch)
    return chars, astral


def gb2312_level1() -> set[str]:
    out: set[str] = set()
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            try:
                out.add(bytes((hi, lo)).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return out


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: subset-cjk-font.py <input-variable.ttf> <output.ttf>")

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    dst.parent.mkdir(parents=True, exist_ok=True)

    repo_chars, astral = collect_chars()
    common = gb2312_level1()
    ascii_chars = {chr(cp) for cp in range(0x20, 0x7F)}
    charset = repo_chars | common | ascii_chars | set(SYMBOL_BUFFER)

    print(f"repo non-ASCII chars: {len(repo_chars)}")
    print(f"gb2312 level-1:       {len(common)}")
    print(f"total subset chars:   {len(charset)}")
    if astral:
        print(f"warn: astral chars found in sources (excluded, will not render): "
              f"{' '.join(sorted(astral))}")

    font = TTFont(str(src))
    if "fvar" in font:
        instantiateVariableFont(font, {"wght": 400}, inplace=True)
        print("instanced variable font at wght=400")

    options = subset.Options()
    options.hinting = False
    options.desubroutinize = True
    options.name_IDs = [1, 2, 3, 4, 6, 13, 14]  # keep family/style/license names
    options.notdef_outline = True
    options.recalc_bounds = True

    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text="".join(sorted(charset)))
    subsetter.subset(font)
    font.save(str(dst))

    out_font = TTFont(str(dst))
    cmap = out_font.getBestCmap()
    probes = "小镇情绪交易人口离线成交未成交图书馆节目继续观看退出×·—…▶◀「」"
    missing = [ch for ch in probes if ord(ch) not in cmap]
    size_mb = dst.stat().st_size / (1024 * 1024)
    print(f"output: {dst} ({size_mb:.2f} MB, {len(cmap)} codepoints)")
    if missing:
        print(f"warn: probe chars missing from subset: {' '.join(missing)}")
    else:
        print("probe chars all present")


if __name__ == "__main__":
    main()
