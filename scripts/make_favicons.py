"""Býr til PNG-útgáfur af static/favicon.svg (gjafamiðanum) með Playwright/Chromium.

favicon-32.png fyrir vafra sem sýna ekki SVG, og apple-touch-icon.png (180×180, ógegnsær
grunnur eins og iOS vill). Keyrt með: uv run python scripts/make_favicons.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parent.parent / "static"
SVG = (STATIC / "favicon.svg").read_text(encoding="utf-8")


def render(page, size: int, path: Path, background: str = "transparent", pad: int = 0) -> None:
    page.set_viewport_size({"width": size, "height": size})
    inner = size - 2 * pad
    page.set_content(
        f"<html><body style='margin:0;background:{background};display:grid;place-items:center;"
        f"width:{size}px;height:{size}px'>"
        f"<div style='width:{inner}px;height:{inner}px'>{SVG}</div></body></html>"
    )
    page.add_style_tag(content="svg{width:100%;height:100%;display:block}")
    page.screenshot(path=path, omit_background=background == "transparent")
    print(path.relative_to(STATIC.parent))


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        render(page, 32, STATIC / "favicon-32.png")
        render(page, 180, STATIC / "apple-touch-icon.png", background="#fff8f6", pad=14)
        browser.close()


if __name__ == "__main__":
    main()
