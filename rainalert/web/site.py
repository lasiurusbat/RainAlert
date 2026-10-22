"""The files a site serves about itself: the crawl rules, the sitemap, the
install manifest, the service worker, and the page for a missing address.
"""

from datetime import date

from flask import (Response, current_app, make_response, render_template,
                   send_from_directory)

from rainalert.data.cities import CURATED_CITIES
from rainalert.present.seo import canonical_url, page_meta


def robots():
    """Where the crawlers may go.

    The alert poll and the calendar export are not pages, and fetching them
    costs two upstream requests each, so they are kept out of the crawl. The
    sitemap says where the pages are.
    """
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /api/",
        "Disallow: /calendar.ics",
        "",
        f"Sitemap: {canonical_url('/sitemap.xml')}",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


def sitemap():
    """The pages of the site, for the crawlers.

    The home page and the city index are here, and so is every city that
    has a page of its own. The dates are today's, because the forecast on
    every one of these pages changes.
    """
    today = date.today().isoformat()
    urls = [
        ("/", "1.0", "daily"),
        ("/cities", "0.8", "weekly"),
        ("/release-notes", "0.4", "monthly"),
    ]
    for slug, _name in CURATED_CITIES:
        urls.append((f"/city/{slug}", "0.7", "daily"))

    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, priority, changefreq in urls:
        body.extend([
            "  <url>",
            f"    <loc>{canonical_url(path)}</loc>",
            f"    <lastmod>{today}</lastmod>",
            f"    <changefreq>{changefreq}</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
        ])
    body.append("</urlset>")
    return Response("\n".join(body) + "\n", mimetype="application/xml")


def page_not_found(error):
    """The page for an address that is not on this site.

    A real ``404`` with a search form on it, rather than Flask's bare
    error page: a crawler that lands on a missing address should be told
    so clearly, and a reader who mistyped one should be able to search
    from there.
    """
    response = make_response(render_template(
        '404.html',
        **page_meta("Page not found - Rain Alert",
                    ("The 7-day rain chance for any city: rain "
                     "unlikely, rain possible or rain likely for every "
                     "day, and today's forecast hour by hour."),
                    "/"),
    ), 404)
    return response


def manifest():
    """The web app manifest, so the site can be installed on a phone.

    It is served from the root so that its scope can be the whole site:
    the page is at "/", the alert poll is at "/api/alert" and the worker is
    at "/service-worker.js", and a manifest served from a subdirectory
    would default to a scope of that subdirectory.
    """
    response = send_from_directory(current_app.static_folder, 'manifest.json')
    response.headers['Content-Type'] = 'application/manifest+json'
    # The manifest names the icons and the colours of the installed app, so
    # a changed one has to reach the phone straight away.
    response.headers['Cache-Control'] = 'no-cache'
    return response


def service_worker():
    """The service worker, served from the root so that it covers the app.

    A worker served from "/static/" would only control "/static/", so it
    is served from the root instead. The Service-Worker-Allowed header is
    belt and braces: the scope of a worker is its own path unless the
    server widens it.
    """
    response = send_from_directory(current_app.static_folder, 'service-worker.js')
    response.headers['Content-Type'] = 'application/javascript'
    response.headers['Service-Worker-Allowed'] = '/'
    # A worker that is cached is a worker that never updates.
    response.headers['Cache-Control'] = 'no-cache'
    return response


def register(app):
    """Add the crawl files, the install files and the 404 page to the app."""
    app.add_url_rule("/robots.txt", view_func=robots)
    app.add_url_rule("/sitemap.xml", view_func=sitemap)
    app.add_url_rule("/manifest.json", view_func=manifest)
    app.add_url_rule("/service-worker.js", view_func=service_worker)
    app.register_error_handler(404, page_not_found)
