"""The security headers every response carries.

The site loads nothing from a third party - the font, the photograph, the
script and the stylesheet are all its own - and the browser half only talks
to the site itself (``/api/alert``), so the policy can be as tight as
``'self'``. The one inline script on a page is the JSON-LD block, which is
data and is not executed, so it needs no allowance.
"""

from flask import request

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'none'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self'",
    "font-src 'self'",
    "connect-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "form-action 'self'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "object-src 'none'",
])

# One year. No includeSubDomains and no preload: those are commitments about
# hosts this app does not control, and the header can be widened later.
STRICT_TRANSPORT_SECURITY = "max-age=31536000"

# Nothing here is used by the app; the notification permission is not a
# policy-controlled feature, so the bell button is not affected.
PERMISSIONS_POLICY = ", ".join([
    "camera=()",
    "microphone=()",
    "geolocation=()",
    "payment=()",
    "usb=()",
    "interest-cohort=()",
])

HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": PERMISSIONS_POLICY,
}


def is_https():
    """Whether the reader reached the site over HTTPS.

    TLS ends at the host's proxy, so the app itself sees plain HTTP and the
    proxy says what the reader used in ``X-Forwarded-Proto``.
    """
    forwarded = request.headers.get("X-Forwarded-Proto", "").split(",")[0]
    return request.is_secure or forwarded.strip().lower() == "https"


def register(app):
    """Add the headers to every response the app sends."""

    @app.after_request
    def add_security_headers(response):
        for name, value in HEADERS.items():
            response.headers.setdefault(name, value)
        # HSTS over plain HTTP is ignored by browsers, so it is only sent
        # where it means something.
        if is_https():
            response.headers.setdefault("Strict-Transport-Security",
                                        STRICT_TRANSPORT_SECURITY)
        return response
