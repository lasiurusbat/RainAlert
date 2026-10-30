"""The files a site serves about itself: the crawl rules, the sitemap, the
install manifest, the service worker, and the page for a missing address.
"""

from datetime import date

from flask import (Response, current_app, make_response, render_template,
                   send_from_directory)

from rainalert.data.cities import CURATED_CITIES
from rainalert.data.releases import RELEASES
from rainalert.present.seo import (NOT_FOUND_DESCRIPTION, NOT_FOUND_TITLE,
                                   canonical_url, page_meta)

# The files the search engines fetch from the root to confirm who owns the
# site, with the type each is served as. They must stay: the engines check
# again to keep the site verified.
VERIFICATION_FILES = {
    "googlee75783b48c054b73.html": "text/html; charset=utf-8",
    "BingSiteAuth.xml": "application/xml",
}


def robots():
    """Where the crawlers may go.

    The alert poll and the calendar export are not pages, and fetching them
    costs two upstream requests each, so they are kept out of the crawl. The
    sitemap says where the pages are.

    Every city page is a forecast the app has to fetch from a rate-limited
    service, so the crawl is slowed down, and SEO crawlers that bring the
    site no readers are kept out altogether.
    """
    lines = [
        "User-agent: SemrushBot",
        "Disallow: /",
        "",
        "User-agent: *",
        "Crawl-delay: 10",
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
    has a page of its own. A city's forecast changes every day, so its date
    is today's. The other pages change only when a release ships, so they
    carry the date of the last release: a date that moved every day would
    tell a crawler nothing.
    """
    today = date.today().isoformat()
    released = RELEASES[0]["date"]
    urls = [
        ("/", "1.0", "daily", released),
        ("/cities", "0.8", "weekly", released),
        ("/release-notes", "0.4", "monthly", released),
    ]
    for slug, _name in CURATED_CITIES:
        urls.append((f"/city/{slug}", "0.7", "daily", today))

    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, priority, changefreq, modified in urls:
        body.extend([
            "  <url>",
            f"    <loc>{canonical_url(path)}</loc>",
            f"    <lastmod>{modified}</lastmod>",
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
        **page_meta(NOT_FOUND_TITLE, NOT_FOUND_DESCRIPTION, "/"),
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


def verification_file(filename):
    """A search engine's site-ownership file, served from the root.

    Google and Bing each look for a file of a given name at the root, and
    the files are a line or two, so each has a route of its own.
    """
    response = send_from_directory(current_app.static_folder, filename)
    response.headers['Content-Type'] = VERIFICATION_FILES[filename]
    return response


def register(app):
    """Add the crawl files, the install files and the 404 page to the app."""
    for filename in VERIFICATION_FILES:
        app.add_url_rule(f"/{filename}", endpoint=filename,
                         view_func=lambda filename=filename: verification_file(filename))
    app.add_url_rule("/robots.txt", view_func=robots)
    app.add_url_rule("/sitemap.xml", view_func=sitemap)
    app.add_url_rule("/manifest.json", view_func=manifest)
    app.add_url_rule("/service-worker.js", view_func=service_worker)
    app.register_error_handler(404, page_not_found)
