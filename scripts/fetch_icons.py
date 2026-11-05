"""Sækir Material Symbols Outlined með aðeins þeim táknmyndum sem kerfið notar.

Allt letrið er ~4 MB; með `icon_names` skilar Google litlu woff2 (nokkur KB). Letrið er hýst
sjálf (persónuvernd og CSP), svo þegar ný táknmynd er notuð þarf að bæta henni við ICONS og
keyra `just icons`.
"""

import re
import sys
import urllib.request
from pathlib import Path

ICONS = [
    "language",
    "link_off",
    "bookmark",
    "ac_unit",
    "add",
    "add_circle_outline",
    "alarm",
    "arrow_back",
    "auto_awesome",
    "calendar_month",
    "calendar_today",
    "card_giftcard",
    "celebration",
    "check",
    "check_circle",
    "close",
    "content_copy",
    "delete",
    "done_all",
    "download",
    "edit",
    "expand_more",
    "group",
    "group_add",
    "history",
    "home",
    "info",
    "lightbulb",
    "link",
    "location_on",
    "lock",
    "lock_open",
    "login",
    "logout",
    "mail",
    "menu",
    "more_horiz",
    "open_in_new",
    "paid",
    "park",
    "payments",
    "person",
    "person_add",
    "person_remove",
    "radio_button_unchecked",
    "redeem",
    "request_quote",
    "save",
    "search",
    "settings",
    "share",
    "sort",
    "speed",
    "star",
    "storefront",
    "undo",
    "upload_file",
    "warning",
]

OUT = Path(__file__).resolve().parent.parent / "static" / "fonts" / "material-symbols.woff2"
CSS_URL = (
    "https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,400,0..1,0"
    "&icon_names={names}&display=block"
)
# Google skilar woff2 aðeins til vafra sem það þekkir
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main() -> int:
    names = ",".join(sorted(set(ICONS)))  # Google krefst stafrófsraðar
    css = fetch(CSS_URL.format(names=names)).decode()
    match = re.search(r"url\((https://[^)]+)\)\s*format\('woff2'\)", css)
    if not match:
        print("Fann ekki woff2-slóð í svari Google:\n" + css, file=sys.stderr)
        return 1
    OUT.write_bytes(fetch(match.group(1)))
    print(f"{len(set(ICONS))} táknmyndir -> {OUT.name} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
