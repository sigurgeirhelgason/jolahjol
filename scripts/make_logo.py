"""Býr til vefútgáfur af merkinu úr upprunamyndinni (PNG með gegnsæjum bakgrunni, ~2 MB).

Sker að merkinu (gegnsær bakgrunnur), og vistar WebP í nokkrum breiddum í static/img/.
Upprunamyndin er ekki í git (of stór); sjálfgefið reff/jolahjol-logo.png.
Keyrt með: uv run --with pillow python scripts/make_logo.py [slóð á mynd]
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "reff" / "jolahjol-logo.png"
OUT = ROOT / "static" / "img"
WIDTHS = (160, 320, 640)


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE
    image = Image.open(source).convert("RGBA")
    # Skera að því sem sést (alfa > 8), með smá spássíu
    alpha = image.getchannel("A").point(lambda v: 255 if v > 8 else 0)
    left, top, right, bottom = alpha.getbbox()
    pad = 12
    image = image.crop((max(0, left - pad), max(0, top - pad), right + pad, bottom + pad))
    OUT.mkdir(exist_ok=True)
    for width in WIDTHS:
        height = round(image.height * width / image.width)
        path = OUT / f"logo-{width}.webp"
        image.resize((width, height), Image.LANCZOS).save(path, "WEBP", quality=88, method=6)
        print(f"{path.relative_to(ROOT)}  {width}×{height}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
