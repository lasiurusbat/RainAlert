"""Generate the social card image from the brand mark.

A link shared from the site is shown as a card with a picture, and the
picture is this file: 1200 by 630 pixels, which is the size the card
formats ask for. The PNG is committed to the repository, so nothing in the
build, the container image or the test suite has to run this. It is here so
that the card can be regenerated when the brand or the wording changes.

The card is the site itself: the night the photograph shows, the mark, the
name, and the week's chance of rain as seven columns - the same figure the
page ends with.

It needs Chrome and selenium:

    pip install -r requirements-dev.txt
    python tools/make_og_image.py
"""

import os
import sys
import tempfile
import urllib.parse

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
except ImportError:
    sys.exit("selenium is not installed. Try: pip install -r requirements-dev.txt")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(REPO, "static")

WIDTH = 1200
HEIGHT = 630

# The mark: the umbrella reduced to one stroke, on the same dark plate the
# site is built on.
MARK = (
    '<rect width="64" height="64" rx="14" fill="#182027"/>'
    '<g fill="none" stroke="#E9EFF2" stroke-width="5" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M9 33c6-20 40-20 46 0"/>'
    '<path d="M32 20v24a8 8 0 0 1-8 8"/>'
    '</g>'
)

# The card: the night street palette. Asphalt, haze, mist and paper, with
# the sodium lamp's amber as the only accent.
PAPER = "#E9EFF2"
MIST = "#8FA3AE"
AMBER = "#E9A93C"
WET = "#5FA8D3"
CALM = "#7C8B94"

# The seven days of the week, and the band each one falls in: the same
# three bands the page uses, so the card and the site agree.
BARS = [
    (30, CALM),
    (55, WET),
    (20, CALM),
    (75, AMBER),
    (45, WET),
    (90, AMBER),
    (35, WET),
]


def bars_svg():
    """Seven columns of rain chance, the way the page draws its week."""
    gap = 22
    width = 46
    left = 664
    bottom = 348
    parts = [
        '<line x1="%.0f" y1="%.0f" x2="%.0f" y2="%.0f" stroke="#2A343B" '
        'stroke-width="2"/>' % (left - 22, bottom, left + 7 * (width + gap) - gap + 22, bottom)
    ]
    for index, (height, colour) in enumerate(BARS):
        top = bottom - height * 1.7
        parts.append(
            f'<rect x="{left + index * (width + gap)}" y="{top:.0f}" '
            f'width="{width}" height="{bottom - top:.0f}" rx="7" fill="{colour}"/>')
    return "".join(parts)


PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@font-face { font-family: 'Archivo'; font-style: normal; font-weight: 400 800;
             font-stretch: 62% 125%; src: url('@@FONT@@') format('woff2'); }
html, body { margin: 0; padding: 0; overflow: hidden; background: #0D1216;
              width: 1200px; height: 630px; }
.card { width: 1200px; height: 630px; position: relative; overflow: hidden;
        background: linear-gradient(160deg, #0D1216 0%, #182027 100%);
        color: #E9EFF2; font-family: 'Archivo', 'Segoe UI', Tahoma, sans-serif; }
/* The lamp at the end of the street. */
.card::after { content: ""; position: absolute; right: -120px; top: -180px;
               width: 620px; height: 620px; border-radius: 50%;
               background: radial-gradient(circle, rgba(233,169,60,0.16) 0%,
                           rgba(233,169,60,0) 70%); }
.mark { position: absolute; left: 84px; top: 132px; width: 132px; height: 132px; }
h1 { position: absolute; left: 84px; top: 316px; margin: 0; font-size: 86px;
     font-variation-settings: 'wdth' 100, 'wght' 700; letter-spacing: -2.5px;
     line-height: 1; }
p { position: absolute; left: 90px; top: 428px; margin: 0; font-size: 32px;
    color: #8FA3AE; font-variation-settings: 'wdth' 74, 'wght' 500; }
.bars { position: absolute; left: 0; top: 0; }
</style></head><body>
<div class="card">
  <div class="mark">@@MARK@@</div>
  <h1>Rain Alert</h1>
  <p>The 7-day rain chance for any city.</p>
  <div class="bars">@@BARS@@</div>
</div>
</body></html>"""


def font_url():
    """The site font, loaded from the repository.

    The card is rendered from a temporary file, so the font cannot be
    referred to relatively - it is addressed by its own file URL.
    """
    path = os.path.join(STATIC, "fonts", "archivo-latin.woff2")
    return "file:///" + urllib.parse.quote(path.replace("\\", "/"))


def render(driver):
    """Rasterise the card and return the PNG bytes."""
    mark = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
            'width="100%" height="100%">' + MARK + '</svg>')
    bars = ('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" '
            'viewBox="0 0 1200 630">' + bars_svg() + '</svg>')
    page = (PAGE.replace("@@MARK@@", mark).replace("@@BARS@@", bars)
            .replace("@@FONT@@", font_url()))
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(page)
        path = handle.name
    try:
        driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": WIDTH, "height": HEIGHT,
            "deviceScaleFactor": 1, "mobile": False,
        })
        driver.get("file:///" + path.replace("\\", "/"))
        return driver.get_screenshot_as_png()
    finally:
        os.unlink(path)


def main():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=options)
    try:
        data = render(driver)
    finally:
        driver.quit()
    target = os.path.join(STATIC, "og-image.png")
    with open(target, "wb") as handle:
        handle.write(data)
    print(f"og-image.png: {WIDTH}x{HEIGHT}, {len(data)} bytes")


if __name__ == "__main__":
    main()
