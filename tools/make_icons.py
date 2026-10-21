"""Generate the PWA icons from the brand mark.

The manifest needs PNG icons - that is what the install prompt and iOS
want - and the mark itself is a vector, so the PNGs are rendered from the
same shapes the favicon uses. The PNGs are committed to the repository:
nothing in the build, the container image or the test suite has to run
this. It is here so the icons can be regenerated when the mark changes.

It needs Chrome and selenium:

    pip install -r requirements-dev.txt
    python tools/make_icons.py
"""

import os
import sys
import tempfile

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
except ImportError:
    sys.exit("selenium is not installed. Try: pip install -r requirements-dev.txt")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(REPO, "static")

# The mark: a white droplet on the brand blue, the same shape the favicon
# uses. The favicon rounds its corners, because a browser tab shows it as a
# square; an installed icon has to fill its canvas, because the platform
# crops it to whatever shape it likes.
DROPLET = (
    '<path d="M32 12c-7 10-13 17.5-13 25a13 13 0 0 0 26 0c0-7.5-6-15-13-25z" fill="#ffffff"/>'
    '<path d="M32 22c-4 6-7.5 10.5-7.5 15a7.5 7.5 0 0 0 5 7.1" fill="none" '
    'stroke="#3498db" stroke-width="2.5" stroke-linecap="round"/>'
)

# A maskable icon is cropped to any shape the platform wants, and only the
# middle 80% is guaranteed to survive, so the mark is scaled down and
# centred for that one.
def icon_svg(scale=1.0):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
        'width="100%" height="100%">'
        '<rect width="64" height="64" fill="#3498db"/>'
        '<g transform="translate(32 32) scale(' + str(scale) +
        ') translate(-32 -32)">' + DROPLET + '</g>'
        '</svg>'
    )


PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
html, body { margin: 0; padding: 0; overflow: hidden; background: #3498db; }
svg { display: block; width: 100vw; height: 100vh; }
</style></head><body>""" + "@@SVG@@" + """</body></html>"""


# The icons the manifest and iOS need. The name says what each one is for.
ICONS = [
    ("icon-192.png", 192, 1.0),
    ("icon-512.png", 512, 1.0),
    ("icon-180.png", 180, 1.0),
    ("icon-maskable-512.png", 512, 0.7),
]


def render(svg, size, driver):
    """Rasterise the SVG at ``size`` pixels square and return the PNG bytes."""
    driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
        "width": size, "height": size,
        "deviceScaleFactor": 1, "mobile": False,
    })
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(PAGE.replace("@@SVG@@", svg))
        path = handle.name
    try:
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
        for name, size, scale in ICONS:
            data = render(icon_svg(scale), size, driver)
            target = os.path.join(STATIC, name)
            with open(target, "wb") as handle:
                handle.write(data)
            print(f"{name}: {size}x{size}, {len(data)} bytes")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
