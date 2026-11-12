"""Býr til deilimyndina (Open Graph, 1200×630) sem Facebook, Messenger o.fl. sýna með hlekk.

Merkið (static/img/logo-640.webp) og slagorðið á vínrauðum grunni, eins og borðinn á síðunni.
Keyrt með: uv run python scripts/make_og_image.py
"""

import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parent.parent / "static"
OUT = STATIC / "img" / "og-image.jpg"


def main() -> None:
    logo = base64.b64encode((STATIC / "img" / "logo-640.webp").read_bytes()).decode()
    # Letrið innbyggt: síða úr set_content má ekki sækja file://-skrár
    jakarta = base64.b64encode((STATIC / "fonts" / "jakarta-latin.woff2").read_bytes()).decode()
    fonts = (
        '@font-face { font-family: "Plus Jakarta Sans"; font-weight: 200 800; '
        f'src: url(data:font/woff2;base64,{jakarta}) format("woff2"); }}'
    )
    html = f"""<html><head><style>{fonts}
      body {{ margin: 0; width: 1200px; height: 630px; overflow: hidden; color: #fff;
        font-family: "Plus Jakarta Sans", sans-serif;
        background:
          radial-gradient(circle at 8% 0%, rgba(107, 2, 23, .7), transparent 40%),
          radial-gradient(circle at 78% 55%, rgba(236, 193, 90, .22), transparent 42%),
          radial-gradient(circle, rgba(255, 255, 255, .07) 1.5px, transparent 2px) 0 0 / 36px 36px,
          #8b1e2b; }}
      .wrap {{ display: flex; align-items: center; gap: 40px; height: 100%;
        padding: 0 72px; box-sizing: border-box; }}
      .text {{ flex: 1; }}
      h1 {{ margin: 0; font-size: 68px; line-height: 76px; font-weight: 800; letter-spacing: -.02em; }}
      p {{ margin: 22px 0 0; font-size: 28px; line-height: 40px; color: #ffdad9; max-width: 560px; }}
      .url {{ display: inline-block; margin-top: 34px; padding: 8px 18px; border-radius: 99px;
        background: rgba(255, 248, 246, .14); color: #ffdf99; font-size: 24px; font-weight: 700; }}
      img {{ width: 470px; transform: rotate(-5deg); filter: drop-shadow(0 24px 40px rgba(40, 0, 8, .55)); }}
    </style></head><body><div class="wrap">
      <div class="text">
        <h1>Minnkaðu jólastressið!</h1>
        <p>Jólagjafirnar, áætlunin og óskalistarnir á einum stað. Ókeypis.</p>
        <span class="url">jolahjol.is</span>
      </div>
      <img src="data:image/webp;base64,{logo}">
    </div></body></html>"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.set_content(html)
        page.wait_for_timeout(300)
        page.screenshot(path=OUT, type="jpeg", quality=88)
        browser.close()
    print(f"{OUT.relative_to(STATIC.parent)}  {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
