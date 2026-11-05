"""Hver táknmynd sem sniðmátin nota verður að vera í letrinu (scripts/fetch_icons.py).

Letrið inniheldur aðeins þær táknmyndir sem eru taldar upp þar. Vanti eina birtist nafnið
hennar sem texti („LANGUAGE“) í stað myndar.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_TAG = re.compile(r"\{%.*?%\}|\{\{.*?\}\}|\{#.*?#\}", re.S)
# class="ms" eða class="ms star lit", en ekki class="msg"
MS_SPAN = re.compile(r'<span class="ms(?: [^"]*)?"[^>]*>([^<]*)</span>', re.S)


def _icons_in_font() -> set[str]:
    source = (ROOT / "scripts" / "fetch_icons.py").read_text(encoding="utf-8")
    block = re.search(r"ICONS = \[(.*?)\]", source, re.S).group(1)
    return set(re.findall(r'"([a-z0-9_]+)"', block))


def _icons_in_templates() -> dict[str, set[str]]:
    used: dict[str, set[str]] = {}
    for path in (ROOT / "templates").rglob("*.html"):
        for content in MS_SPAN.findall(path.read_text(encoding="utf-8")):
            # {% if … %}paid{% else %}request_quote{% endif %} → báðar táknmyndirnar
            for name in re.findall(r"[a-z][a-z0-9_]+", TEMPLATE_TAG.sub(" ", content)):
                used.setdefault(name, set()).add(path.relative_to(ROOT / "templates").as_posix())
    return used


def test_every_icon_used_in_templates_is_in_the_font():
    missing = {name: files for name, files in _icons_in_templates().items() if name not in _icons_in_font()}
    assert not missing, (
        "Táknmyndir vantar í letrið; bættu þeim við ICONS í scripts/fetch_icons.py og keyrðu `just icons`: "
        + ", ".join(f"{name} ({', '.join(sorted(files))})" for name, files in sorted(missing.items()))
    )
