"""The Flask app: :func:`create_app` builds it and registers every route.

The routes are registered on the app itself rather than on blueprints, so
their endpoint names - the names the templates pass to ``url_for`` - stay
the plain function names: ``index``, ``city_page``, ``manifest``.
"""

import logging
import os

from flask import Flask
from flask.logging import default_handler

from rainalert import config
from rainalert.web import api, pages, security, site

# The templates and the static files live at the top of the repository,
# next to the package, not inside it.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def inject_site_info():
    """Make the donation link and the build's identity available to every
    template.

    They are read from the module on each request, not copied at import
    time, so a test can switch the donation link on and off.
    """
    return {
        "donation_url": config.DONATION_URL,
        # Whether the footer has to credit the second source as well.
        "openweather_enabled": bool(config.OPENWEATHER_API_KEY),
        "app_version": config.APP_VERSION,
        "app_commit": config.APP_COMMIT,
    }


def create_app():
    """The app, with its routes, its 404 page and its template globals."""
    app = Flask("rainalert", root_path=ROOT)

    # app.logger is the "rainalert" logger, so the package's own loggers -
    # rainalert.upstream.geocoding and the rest - are its children and print
    # through its handler. It is attached here, before anything logs; Flask
    # would otherwise only attach it the first time app.logger is used.
    logging.getLogger(app.name).addHandler(default_handler)

    app.context_processor(inject_site_info)
    pages.register(app)
    api.register(app)
    site.register(app)
    security.register(app)
    return app
