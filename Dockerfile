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

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

# The slim image ships with no locales beyond C and POSIX, so weekday names
# would always fall back to English. locales-all pulls in the locale data for
# every language the app supports, and localedef then compiles the ones that
# are actually needed into the image.
#
# The list is generated from the app's own tables rather than hardcoded, so
# the image can never drift from what the code claims to support.
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY app.py ./
# The locales package is kept, not purged: the compiled locale data lives in
# /usr/lib/locale, which belongs to that package, so purging it would delete
# the data that was just generated. Only the apt lists and the alias file are
# removed, since the latter is no longer needed once the locales exist.
RUN apt-get update \
    && apt-get install -y --no-install-recommends locales \
    && for loc in $(python -c "import app; print(' '.join(sorted(set(app._LANGUAGE_TO_LOCALE.values()) | set(app._LOCALE_ALIASES.values()))))"); do \
         localedef -i "$loc" -c -f UTF-8 -A /usr/share/locale/locale.alias "$loc.UTF-8" \
         || echo "skipping $loc"; \
       done \
    && rm -rf /var/lib/apt/lists/* /usr/share/locale/locale.alias

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
COPY --chown=rainalert:rainalert templates ./templates
COPY --chown=rainalert:rainalert static ./static

# The test suites come along so that "docker compose run --rm tests" exercises
# exactly the image that gets deployed. They are about 20 KB together.
COPY --chown=rainalert:rainalert test_app.py test_api.py ./

USER rainalert

EXPOSE 8000

# The bind address must be 0.0.0.0. The default 127.0.0.1 would make the
# server unreachable from outside the container.
# One worker with four threads: the app is I/O-bound on two keyless APIs, and
# the geocoding cache is per process, so a single worker keeps the cache warm
# and avoids duplicate Nominatim lookups.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 30 --access-logfile - app:app"]
