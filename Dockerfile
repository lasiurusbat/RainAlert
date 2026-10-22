# RainAlert — container image
#
# Multi-stage so the runtime image carries no build toolchain. The build stage
# compiles the dependency wheels; the runtime stage installs from those wheels
# and never sees a compiler.
#
#   docker build -t rainalert .
#   docker run --rm -p 8000:8000 rainalert
#
# gunicorn needs gunicorn, which is Unix-only. It is in requirements.txt
# because the deployment targets are Linux; this image is Linux, so that is
# exactly right.

# --- Build stage --------------------------------------------------------------
FROM python:3.14-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build the wheels once, in a throwaway layer. Compiling here rather than at
# runtime keeps the runtime image free of a toolchain.
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt


# --- Runtime stage ------------------------------------------------------------
FROM python:3.14-slim AS runtime

# The container's clock is UTC, on purpose. The forecast's dates and hours
# come from the API in the queried city's own time, so the container's
# clock is only ever the server's own clock: the log stamps and the day
# the sitemap says the pages last changed. UTC is the honest answer for
# both, and it needs no locale data in the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    TZ=UTC

# Which build this is. The footer of every page carries the version and the
# commit, so that a reader — and the person looking after the site — can
# see which build is answering. A release build passes them in; a plain
# local build passes neither and says "dev".
#
#   docker build --build-arg APP_VERSION=0.8 --build-arg APP_COMMIT=1a2b3c4 .
ARG APP_VERSION=dev
ARG APP_COMMIT=
ENV APP_VERSION=${APP_VERSION} \
    APP_COMMIT=${APP_COMMIT}

# The image installs no system packages. The weekday names are hard-coded in
# the app, so there is no locale data to compile and nothing to install.
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Run as a non-root user. The application needs no write access anywhere: it
# has no database, no uploads and no instance folder.
#
# The user gets a home directory because gunicorn 26 opens a control socket at
# $HOME/.gunicorn/gunicorn.ctl, and without a writable home it fails with
# "Permission denied" on startup. XDG_RUNTIME_DIR is set as well, since
# gunicorn prefers it when it exists.
RUN groupadd --system --gid 1001 rainalert \
    && useradd --system --uid 1001 --gid rainalert --create-home \
        --home-dir /home/rainalert --shell /usr/sbin/nologin rainalert \
    && mkdir -p /run/rainalert \
    && chown rainalert:rainalert /run/rainalert

ENV XDG_RUNTIME_DIR=/run/rainalert

WORKDIR /app

COPY --chown=rainalert:rainalert app.py ./
COPY --chown=rainalert:rainalert rainalert ./rainalert
COPY --chown=rainalert:rainalert templates ./templates
COPY --chown=rainalert:rainalert static ./static

# The two HTTP test suites come along so that "docker compose run --rm tests"
# exercises exactly the image that gets deployed: the offline suite in
# tests/offline/ and the live one in tests/test_api.py. The browser suite is
# deliberately not here (.dockerignore leaves it out): it drives a real
# headless Chrome, and the image installs no system packages on purpose, so
# it runs on the CI runner instead.
COPY --chown=rainalert:rainalert tests ./tests

# The API reference and its OpenAPI spec come along for the same reason: the
# offline suite checks them against the routes the app actually serves, and
# that check has to run inside the image like the rest of the suite.
COPY --chown=rainalert:rainalert API.md openapi.yaml ./

USER rainalert

EXPOSE 8000

# The bind address must be 0.0.0.0. The default 127.0.0.1 would make the
# server unreachable from outside the container.
# One worker with four threads: the app is I/O-bound on two keyless APIs, and
# the geocoding cache is per process, so a single worker keeps the cache warm
# and avoids duplicate Nominatim lookups.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 30 --access-logfile - app:app"]
