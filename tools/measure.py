"""Measure the page in a real browser: the vertical budget and the boxes.

    python tools/measure.py [url] [width] [height]
"""

import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

SCRIPT = """
const out = {};
const doc = document.documentElement;
out.scroll = doc.scrollHeight - doc.clientHeight;
out.body = document.body.getBoundingClientRect().height;
out.page = document.querySelector('.page').getBoundingClientRect();
out.panel = document.querySelector('.container').getBoundingClientRect();
out.values = document.querySelector('.hourly-values');
out.nowLabel = document.querySelector('.now-label');
out.valueCells = Array.from(
    document.querySelectorAll('.hour-value')).slice(0, 6).map(function (el) {
        return {cell: Math.round(el.getBoundingClientRect().width),
                text: el.textContent.trim(),
                overflow: el.scrollWidth - el.clientWidth};
    });
out.strip = document.querySelector('.hourly-strip').getBoundingClientRect();
out.axis = document.querySelector('.hourly-axis').getBoundingClientRect();
out.days = Array.from(document.querySelectorAll('.weather-item')).map(function (el) {
    const r = el.getBoundingClientRect();
    const c = el.querySelector('.rain-chance').getBoundingClientRect();
    return {day: Math.round(r.width), chance: Math.round(c.width),
            overflow: Math.round(c.width - r.width)};
});
return out;
"""


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5000/city/london"
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 1366
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 768

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
        for key, value in driver.execute_script(SCRIPT).items():
            print(f"{key}: {value}")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
