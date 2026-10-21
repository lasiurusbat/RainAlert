# Deploying RainAlert to Render (free) at rainalert.live

The Docker half of this has been exercised locally: the image builds, both
test suites pass inside it, and a forecast renders with English weekday
names. The Render and GitHub Actions half has **not** been run — the service,
the domain and the first tag push are still ahead. `render.yaml` points at
the Docker Hub image `lasiurusbat/rainalert:0.8`, which does not exist yet.

## 1. Build and push the image (manual, first release)

Render pulls a prebuilt image; it does not build the Dockerfile. Once the
pipeline in section 5 is set up, releases are done by pushing a git tag instead
and these commands are only a fallback.

```bash
docker build --platform linux/amd64 -t lasiurusbat/rainalert:0.8 .
docker login
docker push lasiurusbat/rainalert:0.8
```

Render runs `linux/amd64`. Use a new tag for every release (0.9, 1.0, ...)
rather than `latest`, so it is clear which version is live. If the Docker Hub
repository is private, add a registry credential in Render (Workspace
Settings) and reference it under `image:` in `render.yaml` (see the comment
there).

## 2. Create the service

1. Commit `render.yaml` and push the repository to GitHub (the repo is
   already connected at `github.com/lasiurusbat/RainAlert`).
2. Render dashboard → **New → Blueprint** → select the repository.
3. Render proposes a free web service named `rainalert` running
   `docker.io/lasiurusbat/rainalert:0.8`. Apply it.
4. Open the `*.onrender.com` URL and search a city to confirm it works.
   (The first request after idle takes about a minute: free-tier cold start.)
5. To release a new version: push the new tag, edit the tag in `render.yaml`
   (or the service settings), and redeploy. Render is not assumed to pick up
   new pushes by itself.

`DONATION_URL` (the Buy Me a Coffee link) is set in `render.yaml`. Changing or
removing it needs a redeploy of the service but no new image, because the
image reads it at start-up. Remove the line, or leave it empty, to hide the
donation link.

## 3. Attach the domain

1. Service → **Settings → Custom Domains → + Add Custom Domain** →
   `rainalert.live`. `www.rainalert.live` is added and redirected to the root.
2. At your DNS provider, delete any `AAAA` records for the domain, then add the
   records Render shows (copy the exact values from the dashboard).
3. Click **Verify**. Wait and retry if DNS has not propagated yet.
4. Render issues the HTTPS certificate automatically and redirects HTTP to HTTPS.
   A brief 502 right after verifying usually means routing is still updating.

## 4. Optional

- Add a free uptime pinger (e.g. UptimeRobot) on `https://rainalert.live/` to
  avoid cold starts. Free instances get 750 hours a month, enough for one
  always-on service.
- Free-tier limits: 512 MB RAM, 5 GB bandwidth, wiped filesystem on restart,
  single instance. Re-check https://render.com/docs/free before relying on them.

## 5. CI/CD pipeline (GitHub Actions)

The workflow is `.github/workflows/ci-cd.yml`. It has not been run yet.

```
pull request / push to main          push of a tag such as v0.9
        |                                      |
  build image (linux/amd64)             build image (linux/amd64)
  run unit tests inside it              run unit tests inside it
        |                               verify the tag is on main
      done                              docker push lasiurusbat/rainalert:0.9
                                                |
                                        Render deploy hook with that tag
                                                |
                                        smoke test https://rainalert.live/
```

### Design decisions

- **Tests run inside the image.** The suite needs nothing from the host now
  that the weekday names are hard-coded, so it would pass on a stock GitHub
  runner too. It still runs in the built image, because that is what makes
  the tested artefact and the shipped artefact the same one.
- **One build, tested then pushed.** The image that passed the tests is the
  one that is pushed. It is not rebuilt for the push.
- **Releases are git tags.** Push `v0.9` and the image is tagged `0.9`.
  Tags must look like `v0.9` or `v1.2.3` and must point at a commit already
  on `main`; anything else fails before anything is pushed.
- **Deploys name the exact tag.** Render does not redeploy an image service
  when a new image appears on Docker Hub. The workflow calls the service's
  deploy hook with an `imgURL` parameter, which Render's docs describe for
  choosing a tag. Everything except the tag must match the service's default
  image URL (`docker.io/lasiurusbat/rainalert`).
- **Pull requests never push or deploy.** Secrets are only used on tag runs.

### One-time setup

1. **Docker Hub:** Account Settings -> Personal access tokens -> new token
   with Read & Write scope. Never use the account password.
2. **Render:** service -> Settings -> Deploy Hook -> copy the URL. Treat it as
   a secret: anyone with it can trigger deploys.
3. **GitHub:** repository -> Settings -> Secrets and variables -> Actions ->
   add `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `RENDER_DEPLOY_HOOK_URL`.
4. **GitHub (optional):** Settings -> Environments -> `production` -> add
   yourself as a required reviewer for a manual approval before each deploy.
5. **GitHub (recommended):** protect `main` and require the
   `build-test-push` check before merging.

### Releasing

```bash
git switch main && git pull
git tag v0.9
git push origin v0.9
```

Watch the run under the repository's Actions tab. The first release after
setup is `v0.8`, to match `render.yaml`, which pins `0.8`.

### Known limits

- **Not run yet.** The image builds and the tests pass inside it locally,
  but the workflow itself has never executed, and neither has a Render
  deploy. Expect to fix small things on the first run, and use a throwaway
  tag for it. The image `lasiurusbat/rainalert:0.8` does not exist on Docker
  Hub yet, so section 1 is still ahead.
- **Action versions are not verified as the latest.** The workflow uses
  `actions/checkout@v4`, `docker/setup-buildx-action@v3`,
  `docker/build-push-action@v6` and `docker/login-action@v3`.
  `.github/dependabot.yml` keeps these current: every Monday 07:00 (Berlin)
  Dependabot opens one grouped PR for GitHub Actions, one for the pinned
  packages in `requirements.txt`, and one for the Dockerfile base image.
  Each PR runs the pipeline's tests, so merge only when it is green. The
  first PRs may appear right after the first push to GitHub.
- **Deploy hooks on the free plan.** Render's deploy-hooks page does not say
  whether the free plan includes them. Check the service's Settings page.
  If there is no hook, redeploy manually from the dashboard after each push.
- **`render.yaml` tag drift.** A hook deploy with `imgURL` selects the tag
  for that deploy. I could not confirm whether it also changes the service's
  stored default image, so after a release also update the tag in
  `render.yaml` and the service settings so a later manual redeploy or
  restart does not bring back an older version.
- **The smoke test is shallow.** It confirms `https://rainalert.live/`
  answers, not that the new version is the one answering, because the app
  does not expose its version. If that matters, add a `/healthz` route that
  returns the version.
- **The test counts drift.** The count appears in **four** documents —
  `CLAUDE.md`, `README.md`, `DEPLOY.md` and `implementation-plan.md` — and
  they are updated together, but a test added without updating all four
  leaves them disagreeing. The suite has 169 offline tests and 6 live
  integration tests.
