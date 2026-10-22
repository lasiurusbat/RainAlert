"""Screenshot one element of the running app, for looking at a detail.

    python tools/crop.py [url] [selector] [out.png] [width] [height]
"""

import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000/city/london"
    selector = sys.argv[2] if len(sys.argv) > 2 else ".container"
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(REPO, "crop.png")
    width = int(sys.argv[4]) if len(sys.argv) > 4 else 1366
    height = int(sys.argv[5]) if len(sys.argv) > 5 else 768

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--hide-scrollbars")
    driver = webdriver.Chrome(options=options)
    try:
        driver.set_window_size(width, height + 120)
        driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": 3, "mobile": False,
        })
        driver.get(url)
        time.sleep(2.5)
        element = driver.find_element("css selector", selector)
        element.screenshot(out)
        print(f"{out}: {selector}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
