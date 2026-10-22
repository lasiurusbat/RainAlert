# Deploying RainAlert to Render (free) at rainalert.live

**The site is live at <https://rainalert.live/>.** The Docker half has been
exercised for real: the image builds, both test suites pass inside it, and
a forecast renders with English weekday names. The CI workflow itself has
run and is green on every push to `main`. The **tag-gated half has fired**
— `v1.0` was cut on 2026-10-22 — the image it built **has been pushed to
Docker Hub**, and the deploy hook has put it on the service.

State of the world, checked on 2026-10-22:

- **The first release tag exists** (`v1.0`, on `main`), and the workflow's
  push-and-deploy half has run **green**, on its fifth attempt. The
  earlier four failed at the Docker Hub login, the Docker Hub push, the
  browser suite and the deploy hook, in that order; the causes are in
  "Known limits" below.
- **The Docker Hub repository `lasiurusbat/rainalert` is public and has
  one tag**: `1.0`, pushed on 2026-10-22, which is the image `render.yaml`
  points at.
- **The app answers at <https://rainalert.live/>** — the real page, on the
  `1.0` image, with the footer reading "Version 1.0 · build 7265a18".
  `http://` redirects to `https://`.
- **The service is named `rainalert-1-0`**, because an older service
  already held the name `rainalert`.
- **A Render service named `rainalert` answers at
  <https://rainalert.onrender.com>, and it is not this app.** Its `/`
  returns the JSON `{"message": "Rain Alert API is running 🌂", "status":
  "ok"}`; this app's `/` renders the HTML page. It is a minimal service
  that happens to share the name, and it should be deleted.

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

**Saving a new image does not deploy anything.** This is the one that
catches people: an image-backed service is never redeployed automatically,
because auto-deploy only applies to Git-connected services. Changing the
image URL in the service's settings changes what the *next* deploy will
pull, and nothing else — the old container keeps serving, and it keeps
serving the old version without any sign that anything is wrong. The
deploy is a separate action, and there are three ways to make it:

- **Deploys → Manual Deploy → Deploy latest reference**, in the
  dashboard. It re-pulls the image at the configured tag.
- **The deploy hook**, `GET`/`POST` on the service's hook URL. This is
  what the workflow calls, and it can name a tag with `imgURL`.
- **The API**, `POST /v1/services/{id}/deploys` with the image URL.

Whichever one you use, check the result: the footer of the live page
carries the version and the commit of the build that is answering, so a
`curl` for `Version` on the live address tells you which build is really
there.

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
- Confirm that a city's address the geocoder does not know answers `404`
  and not `200`. A page that says "not found" but answers `200` is a soft
  404, and search engines treat it as one. **Do not use a made-up name
  for this check that happens to be a real place**: `/city/atlantis`
  answers `200`, correctly — there is an Atlantis in New Jersey, and the
  geocoder finds it. A name no geocoder has, such as `/city/zzzqxkvv`,
  answers `404`.
- Confirm that `https://rainalert.live/city/---` answers `404` too. An
  address made only of punctuation stands for no city, so there is no
  page there and no redirect to one.

All of the above were checked on 2026-10-22, on the live domain, and all
of it behaves as written. The only thing left is to submit the sitemap to
the two search engines, and to delete the old stub service.

## 4. Optional

- Add a free uptime pinger (e.g. UptimeRobot) on `https://rainalert.live/` to
  avoid cold starts. Free instances get 750 hours a month, enough for one
  always-on service.
- Free-tier limits: 512 MB RAM, 5 GB bandwidth, wiped filesystem on restart,
  single instance. Re-check https://render.com/docs/free before relying on them.

## 5. CI/CD pipeline (GitHub Actions)

The workflow is `.github/workflows/ci-cd.yml`. The build-and-test half runs
on every push to `main` and is green. The tag-gated half — the push and
the deploy — fired on `v1.0` and failed at the push; the deploy half has
never run.

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
   with Read & Write scope. Never use the account password. A token with
   the **Read** scope alone logs in fine and then fails at the push with
   `unauthorized: access token has insufficient scopes` — the token has to
   be able to write, not only to read.
2. **Render:** service -> Settings -> Deploy Hook -> copy the URL. Treat it as
   a secret: anyone with it can trigger deploys. Take it from the service
   that runs the image — a hook is per-service, and a hook from a
   different service deploys that one instead.
3. **GitHub:** repository -> Settings -> Secrets and variables -> Actions ->
   add `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `RENDER_DEPLOY_HOOK_URL`.
   The username is the Docker Hub account name, not an email address.
   A missing `RENDER_DEPLOY_HOOK_URL` fails the deploy job with
   `curl: (3) URL rejected: Bad hostname` — the hook URL was empty, and
   curl was asked to fetch nothing.
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

**A failed run cannot be fixed with "Re-run failed jobs".** The release run
is pinned to the commit the tag points at, so the button replays the old
workflow against the old commit, and a test that was fixed in a later
commit fails again in exactly the same way. To get a fix into a release
run, the tag has to point at it:

```bash
git tag -f v1.0 <commit> && git push --force origin v1.0
```

That is safe on a tag that never produced a published image, because
nothing that was released moves. On a tag that *was* released, cut a new
version instead.

**Cutting a release means adding an entry to `rainalert/data/releases.py`.** The release
notes page at `/release-notes` is a page of the site, and it says what each
release brought. Add the new release at the top of `RELEASES`, with the
version the tag carries and the features it brought, and the footer of
every page will link to it. The top entry's version is the one the build
stamps into the footer, so the page and the running build agree.

**Bump `CACHE_VERSION` if the release changes the shell.** The shell is
the stylesheet, the script, the icons, the font and the background photo —
the files that make the page *look* like Rain Alert. The service worker
caches them, and a reader who has the app installed gets the cached copy
until the cache version changes. So if the release touches
`static/style.css`, `static/app.js`, an icon or the font, bump
`CACHE_VERSION` in `static/service-worker.js` in the same commit.

This is easy to forget, because the app still *works*: the page comes up
and the forecast is right, and only the styles are old. The rule is
"bump it when the shell changes", and the file to look at is
`static/service-worker.js`, where the version is the first constant.

### Known limits

- **The first release took five attempts**, and the causes are worth
  knowing, because each one is a step of the pipeline rather than a fault
  in the app: the Docker Hub secrets were not set (attempt 1), the token
  had the Read scope and a push needs Read & Write (attempt 2), the
  browser suite flaked on a service-worker wait that was waiting for the
  wrong thing (attempt 3), and the deploy hook secret was not set
  (attempt 4). Attempt 5 was green from end to end.
- **The smoke test is a real check, and it can fail honestly.** It hits
  `https://rainalert.live/` and greps the answer for `Version <tag>`, so
  it proves the new build is the one answering and not an old one. On the
  first release it could not pass, because the domain was still on
  Namecheap forwarding and answered nothing; the deploy had succeeded and
  the run still ended red. If it fails now, read it as "the domain is not
  answering with the new build" — look at the live footer — rather than
  "the deploy broke".
- **A resolver can still hold the old forwarding record.** The domain used
  to be on Namecheap URL forwarding, and a local resolver can keep
  answering with the forwarder's address long after the records changed.
  The connection then times out, which looks exactly like the site being
  gone. Ask a public resolver what the domain is
  (`nslookup rainalert.live 1.1.1.1`) before believing that; a CNAME to
  `rainalert-1-0.onrender.com` and `216.24.57.16` are the right answers.
  `ipconfig /flushdns` clears the local cache.
- **Action versions are not verified as the latest.** The workflow uses
  `actions/checkout@v4`, `docker/setup-buildx-action@v3`,
  `docker/build-push-action@v6` and `docker/login-action@v3`.
  `.github/dependabot.yml` keeps these current: every Monday 07:00 (Berlin)
  Dependabot opens one grouped PR for GitHub Actions, one for the pinned
  packages in `requirements.txt`, and one for the Dockerfile base image.
  Each PR runs the pipeline's tests, so merge only when it is green. The
  first PRs may appear right after the first push to GitHub.
- **A live page can answer `503`, and that is the app working.** The
  forecast service and the geocoder are third parties, and either can be
  unreachable or slow at the moment a reader arrives. A city's page then
  answers `503` and says the service is unavailable; the start page
  answers `200`, because a failed *search* is not a missing *page*. A
  `503` on the live site is worth a look at the Render logs and at
  Open-Meteo's status, not a redeploy.
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
  leaves them disagreeing. The suite has 520 offline tests, 105 browser
  tests and 7 live integration tests.
