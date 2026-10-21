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
