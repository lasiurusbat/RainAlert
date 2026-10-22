"""Take a screenshot of the running app, for looking at the design.

    python tools/shoot.py [url] [out.png] [width] [height]
"""

import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000/city/london"
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(REPO, "shot.png")
    width = int(sys.argv[3]) if len(sys.argv) > 3 else 1366
    height = int(sys.argv[4]) if len(sys.argv) > 4 else 768

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--hide-scrollbars")
    driver = webdriver.Chrome(options=options)
    try:
        driver.set_window_size(width, height + 120)
        driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height,
            "deviceScaleFactor": 1, "mobile": False,
        })
        driver.get(url)
        time.sleep(2.5)
        driver.save_screenshot(out)
        overflow = driver.execute_script(
            "return document.documentElement.scrollHeight - "
            "document.documentElement.clientHeight;")
        print(f"{out}: {width}x{height}, overflow {overflow}px")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
