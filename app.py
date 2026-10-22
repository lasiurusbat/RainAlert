"""RainAlert: look up the 7-day rain chance for any city.

Two free, keyless APIs are used:
  * Nominatim (OpenStreetMap) turns a city name into coordinates.
  * Open-Meteo returns the daily forecast for those coordinates.

This file is the entry point - ``python app.py`` for development, and
``gunicorn app:app`` in the image. The app itself is built by
:func:`rainalert.web.create_app`.
"""

import os

from rainalert.web import create_app

app = create_app()


if __name__ == '__main__':
    app.run(debug=os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"})
