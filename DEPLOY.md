# Deploying RainAlert to Render (free) at rainalert.live

**The site is not live.** The Docker half of this has been exercised
locally: the image builds, both test suites pass inside it, and a forecast
renders with English weekday names. The CI workflow itself has run and is
green on every push to `main`, but the **tag-gated half has never fired** —
no release has been pushed and no deploy has been requested.

State of the world, checked on 2026-10-22:

- **No release tag exists** (`git tag -l` is empty), so the image has never
  been pushed.
- **The Docker Hub repository `lasiurusbat/rainalert` exists and is
  public, but it has zero tags** (the API answers
  `{"count":0,...}`). `render.yaml` points at
  `lasiurusbat/rainalert:1.0`, which does not exist.
- **A Render service named `rainalert` answers at
  <https://rainalert.onrender.com>, but it is not this app.** Its `/`
  returns the JSON `{"message": "Rain Alert API is running 🌂", "status":
  "ok"}`; this app's `/` renders the HTML page. It looks like a minimal
  service that happens to share the name, and it has to be replaced or
  repointed at the real image.
- **`rainalert.live` is on Namecheap URL forwarding and answers nothing.**
  `http://rainalert.live/` answers `302` with `X-Served-By: Namecheap
  URL Forward` and points at `http://www.rainalert.live/`, whose A record
  is `0.0.0.0` — so the second hop answers nothing, and `https://` on the
  root does not answer at all. No Render address is in the DNS.

The order matters: the image has to exist on Docker Hub before Render can
pull it, and the domain has to be attached before the workflow's smoke test
can pass.

## 1. Build and push the image (manual, first release)

Render pulls a prebuilt image; it does not build the Dockerfile. Once the
pipeline in section 5 is set up, releases are done by pushing a git tag instead
and these commands are only a fallback.

```bash
docker build --platform linux/amd64 \
  --build-arg APP_VERSION=1.0 --build-arg APP_COMMIT=$(git rev-parse --short HEAD) \
  -t lasiurusbat/rainalert:1.0 .
docker login
docker push lasiurusbat/rainalert:1.0
```

Render runs `linux/amd64`. Use a new tag for every release (0.9, 1.0, ...)
rather than `latest`, so it is clear which version is live. If the Docker Hub
repository is private, add a registry credential in Render (Workspace
Settings) and reference it under `image:` in `render.yaml` (see the comment
there).

**The two build args stamp the image.** `APP_VERSION` is the number of the
release and `APP_COMMIT` is the short commit it was built from; both end
up in the footer of every page, under the data credits, so the site says
which build is answering. The CI workflow passes them automatically, and
the smoke test in section 5 reads the version back off the live page. A
build with neither says "Version dev", which is the honest answer for a
working tree.

## 2. Create the service

1. Commit `render.yaml` and push the repository to GitHub (the repo is
   already connected at `github.com/lasiurusbat/RainAlert`).
2. Render dashboard → **New → Blueprint** → select the repository.
3. Render proposes a free web service named `rainalert` running
   `docker.io/lasiurusbat/rainalert:1.0`. Apply it.
4. Open the `*.onrender.com` URL and search a city to confirm it works.
   (The first request after idle takes about a minute: free-tier cold start.)
5. To release a new version: push the new tag, edit the tag in `render.yaml`
   (or the service settings), and redeploy. Render is not assumed to pick up
   new pushes by itself.

`DONATION_URL` (the Buy Me a Coffee link) is set in `render.yaml`. Changing or
removing it needs a redeploy of the service but no new image, because the
image reads it at start-up. Remove the line, or leave it empty, to hide the
donation link.

`SITE_URL` (the site's own address, used for the canonical link, the social
card, the sitemap and the structured data) defaults to
`https://rainalert.live`. Set it explicitly in `render.yaml` if the service
is ever served from a different address — a canonical link pointing
somewhere other than where the site lives is worse than none at all.

Two settings in `render.yaml` are worth knowing about:

- **`autoDeploy: false`.** The service is deployed by the hook, which
  names the tag it wants. Left on, auto-deploy would redeploy the service
  with the *stored* image — the fallback tag in the file — as soon as any
  image was pushed to Docker Hub, which is how an old version comes back.
- **`healthCheckPath: /`.** The app has no separate health endpoint: its
  home page is the app's own page, and a `200` from it means the server is
  up and serving.

## 3. Attach the domain

1. Service → **Settings → Custom Domains → + Add Custom Domain** →
   `rainalert.live`. `www.rainalert.live` is added and redirected to the root.
2. At your DNS provider, delete any `AAAA` records for the domain, then add the
   records Render shows (copy the exact values from the dashboard).
3. Click **Verify**. Wait and retry if DNS has not propagated yet.
4. Render issues the HTTPS certificate automatically and redirects HTTP to HTTPS.
   A brief 502 right after verifying usually means routing is still updating.

### After the domain works

The site is built to be found by search engines, and the pieces of it that
need the live domain are the absolute addresses in the page head and in
`sitemap.xml`. Once `https://rainalert.live` answers with the app's own
page:

- Check `https://rainalert.live/robots.txt` and
  `https://rainalert.live/sitemap.xml` in a browser. The sitemap should
  list the start page, `/cities` and one `/city/<slug>` for each of the 92
  curated cities.
- Open `https://rainalert.live/city/london` and look at the page source: the
  canonical link, the Open Graph image and the JSON-LD should all point at
  `https://rainalert.live`. If they point at a different host, `SITE_URL` is
  wrong and needs a redeploy.
- Submit `https://rainalert.live/sitemap.xml` in
  [Google Search Console](https://search.google.com/search-console) and in
  [Bing Webmaster Tools](https://www.bing.com/webmasters). Both are free
  and both want the sitemap, not a verification tag in the markup.
- Confirm that `https://rainalert.live/city/atlantis` answers `404` and not
  `200`. A page that says "not found" but answers `200` is a soft 404, and
  search engines treat it as one.

## 4. Optional

- Add a free uptime pinger (e.g. UptimeRobot) on `https://rainalert.live/` to
  avoid cold starts. Free instances get 750 hours a month, enough for one
  always-on service.
- Free-tier limits: 512 MB RAM, 5 GB bandwidth, wiped filesystem on restart,
  single instance. Re-check https://render.com/docs/free before relying on them.

## 5. CI/CD pipeline (GitHub Actions)

The workflow is `.github/workflows/ci-cd.yml`. The build-and-test half runs
on every push to `main` and is green; only the tag-gated half — the push and
the deploy — has never fired.

```
pull request / push to main          push of a tag such as v1.0
        |                                      |
  build image (linux/amd64)             build image (linux/amd64)
  run unit tests inside it              run unit tests inside it
  run browser tests on the runner       run browser tests on the runner
        |                               verify the tag is on main
      done                              docker push lasiurusbat/rainalert:1.0
                                                |
                                        Render deploy hook with that tag
                                                |
                                        smoke test: does the live page
                                        carry "Version 1.0"?
```

### Design decisions

- **Tests run inside the image.** The suite needs nothing from the host now
  that the weekday names are hard-coded, so it would pass on a stock GitHub
  runner too. It still runs in the built image, because that is what makes
  the tested artefact and the shipped artefact the same one.
- **The browser tests run on the runner.** `tests/test_browser.py` drives a real
  headless Chrome, and the image installs no system packages on purpose, so
  Chrome cannot be in it. The runner has Chrome already, so that suite runs
  there instead, against the same source. It runs **before** the push, so a
  failing browser test means the image is never pushed at all.
- **One build, tested then pushed.** The image that passed the tests is the
  one that is pushed. It is not rebuilt for the push.
- **Releases are git tags.** Push `v1.0` and the image is tagged `1.0`.
  Tags must look like `v1.0` or `v1.2.3` and must point at a commit already
  on `main`; anything else fails before anything is pushed.
- **Deploys name the exact tag.** Render does not redeploy an image service
  when a new image appears on Docker Hub. The workflow calls the service's
  deploy hook with an `imgURL` parameter, which Render's docs describe for
  choosing a tag. Everything except the tag must match the service's default
  image URL (`docker.io/lasiurusbat/rainalert`).
- **The build is stamped with its version and commit.** The workflow passes
  `APP_VERSION` and `APP_COMMIT` as build args, and the footer of every
  page carries them. The smoke test then reads the version back off the
  live page, so it can tell "the site is up" from "the new build is up".
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
git tag v1.0
git push origin v1.0
```

Watch the run under the repository's Actions tab. The first release after
setup is `v1.0`, to match `render.yaml`, which pins `1.0`.

**Cutting a release means adding an entry to `rainalert/data/releases.py`.** The release
notes page at `/release-notes` is a page of the site, and it says what each
release brought. Add the new release at the top of `RELEASES`, with the
version the tag carries and the points that release made, and the footer of
every page will link to it. The top entry's version is the one the build
stamps into the footer, so the page and the running build agree.

### Known limits

- **Not run yet.** The image builds and the tests pass inside it locally,
  and the CI workflow runs green on every push to `main`, but the tag-gated
  half — the push and the deploy — has never executed. Expect to fix small
  things on the first release, and use a throwaway tag for it. The image
  `lasiurusbat/rainalert:1.0` does not exist on Docker Hub yet, so section 1
  is still ahead.
- **The smoke test will fail on the first release.** It hits
  `https://rainalert.live/`, which still answers nothing while the domain
  is on Namecheap forwarding. The deploy can succeed and the run still ends
  red. Attach the domain first, or read the failed smoke test as "the
  domain is not attached yet" rather than "the deploy broke".
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
- **The smoke test reads the version, not just the page.** The footer of
  every page carries the version of the build that answered it, so the
  smoke test greps for `Version <tag>` and can tell "the site is up" from
  "the new build is up". It is still a check of one page from outside —
  it does not exercise a forecast, and it cannot see which upstream data
  the page was rendered from.
- **The test counts drift.** The count appears in **four** documents —
  `CLAUDE.md`, `README.md`, `DEPLOY.md` and `implementation-plan.md` — and
  they are updated together, but a test added without updating all four
  leaves them disagreeing. The suite has 513 offline tests, 105 browser
  tests and 7 live integration tests.
