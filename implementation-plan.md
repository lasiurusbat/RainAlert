# RainAlert implementation plan

Status as of 2026-10-21. Checked items (`[x]`) are finished and can be seen in
the repository. Unchecked items (`[ ]`) are open. Items marked **(verify)** may
already be done, but nothing in the repository proves it, so they stay open
until confirmed.

Live site: <https://rainalert.live> (planned). Image: `lasiurusbat/rainalert`.
Repository: <https://github.com/lasiurusbat/RainAlert>.

## 1. Where we are

The app works locally, is containerised, has a CI/CD pipeline and Dependabot
committed and pushed to GitHub, and has a deployment runbook. No release tag
exists yet, so nothing is confirmed live. The alert features are only partly
built: the page colour-codes rain risk and shows an hour-by-hour strip for
today with a "bring an umbrella" summary, but nothing yet notifies a user who
is not already looking at the page.

The hourly-strip work and the donation/attribution work are both in the
working tree and not in a commit yet. `app.py`, the template, the stylesheet,
`render.yaml`, both test suites and the screenshot are modified, and this plan
file is itself untracked.

## 2. Finished

### Core app
- [x] Flask app: city name -> coordinates (Nominatim) -> 7-day forecast (Open-Meteo)
- [x] Separate error handling for "city not found", geocoder down and weather service down
- [x] Geocoding cache, explicit timeouts, configuration through environment variables
- [x] City-local dates (`timezone=auto`) and localised weekday names with a safe English fallback
- [x] Temperature rounding fix (round half up)
- [x] Offline unit tests (110) and live API tests (6)
- [x] Comprehensive `README.md` with screenshot, `CLAUDE.md` project notes

### Alert ideas, Tier 1 (partly done)
- [x] Visual rain severity: three colour bands, legend, tinted rows, dots
- [x] Umbrella icon on days at or above the umbrella threshold
- [x] Screen-reader labels for each severity band
- [x] Thresholds configurable (`SEVERITY_LOW_MAX`, `SEVERITY_MODERATE_MAX`, `UMBRELLA_THRESHOLD`)
- [x] Hour-by-hour strip for today: 24 bars for the city's local day, a one-line summary ("Rain likely from about 15:00 to 16:00, up to 83%. Bring an umbrella."), a pulsing dot on the current hour, and a table view so no value is hover-only

### Packaging and delivery
- [x] Multi-stage `Dockerfile`: non-root user, locale data installed, tests included in the image
- [x] `.dockerignore`, `.gitignore`, `docker-compose.yml` (app plus a `tests` profile)
- [x] `render.yaml`: free web service running `docker.io/lasiurusbat/rainalert:0.8`, English weekday names (`DATE_LOCALE=C`), user agent naming rainalert.live
- [x] `.github/workflows/ci-cd.yml`: build, test in the image, push on release tag, Render deploy hook, smoke test
- [x] `.github/dependabot.yml`: weekly updates for Actions, pip and the Docker base image
- [x] `DEPLOY.md` runbook (image push, Render setup, domain, pipeline, known limits)
- [x] Code committed and pushed to GitHub (`origin/main`); Dependabot has already opened a branch

### Decisions made
- [x] Hosting: Render free tier with prebuilt Docker Hub image (Cloud Run rejected: needs a card, domain mapping and load balancer costs)
- [x] Custom domain `rainalert.live` on Render (free plan lists custom domains and managed TLS)
- [x] Ads and affiliate links deferred. Open-Meteo's free API is non-commercial: ads, subscriptions and promotions would need a paid plan. Voluntary donations are allowed.
- [x] Revenue: donations through Buy Me a Coffee

## 3. Go-live checklist (needs your accounts)

These steps use accounts and dashboards I cannot see from the repository.

- [ ] Docker Hub: create the `lasiurusbat/rainalert` repository (public) and an access token with Read & Write scope. Confirmed 2026-10-21: neither exists yet.
- [ ] **(verify)** GitHub secrets set: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `RENDER_DEPLOY_HOOK_URL`
- [ ] Render: create the Blueprint from the repository so the service `rainalert` exists. Confirmed 2026-10-21: it does not exist yet.
- [ ] Confirm the free Render service has a deploy hook (docs do not say) and add its URL as a GitHub secret. If not, plan on manual redeploys.
- [ ] Note the order: the image must exist on Docker Hub before the Render Blueprint is created, or Render's first deploy fails to pull it
- [ ] **(verify)** Domain: `rainalert.live` added in Render, `AAAA` records removed, DNS records added, verified, HTTPS working
- [ ] GitHub: protect `main`, require the `build-test-push` check, optionally add a reviewer to the `production` environment
- [ ] Review and merge (or close) the open Dependabot pull request once its checks pass
- [ ] Cut the first release: tag `v0.8` on `main` and push it (no tag exists yet)
- [ ] Watch the first pipeline run, fix anything small it turns up (workflow has never been executed)
- [ ] Open the live site, search a city, confirm forecast and English weekday names
- [ ] Optional: free uptime pinger on `https://rainalert.live/` to avoid the one-minute cold start

## 4. Attribution and donations (built, ships in v0.8)

Buy Me a Coffee fits the free Open-Meteo terms only if it stays voluntary
one-off donations. Do not use its memberships, shop or paid-extras features:
those would make the site commercial.

**Prerequisites (you)**
- [x] Buy Me a Coffee page created: <https://buymeacoffee.com/rainalert> (page was live and showed the agreed bio when checked on 2026-10-21)
- [ ] On the Buy Me a Coffee page, turn off **Memberships** (it currently lists a monthly $1 option) and the **extras/checkout** link, and hide any "make support monthly" option if the settings allow it. Open-Meteo's free terms allow voluntary donations but call sites with subscriptions commercial. A recurring monthly membership sits close enough to that line to be worth removing, or to ask info@open-meteo.com about before launch.
- [ ] Read Buy Me a Coffee's current fees, payout and country terms before launching the link
- [x] Wording decided: "Saved you from getting wet? Buy me a coffee and help keep Rain Alert free."

**Design decisions (already taken)**
- Plain text link, not the embedded widget or script. A script would load third-party code and may need a consent notice; a link does not.
- The URL comes from an environment variable that is empty by default. With it empty, no donation link renders, so tests and local runs behave as today.
- Placement: one line under the forecast results, shown only when a forecast is displayed, and again in the footer. Nothing near the search box, no pop-ups.
- Link opens in a new tab with `noopener`; label it clearly as a donation link.
- Attribution to Open-Meteo is required by its licence (CC BY 4.0) and the page shows none yet, so it ships in the same release: "Weather data by Open-Meteo.com" with a link, plus the existing Nominatim/OpenStreetMap credit if the geocoder data is shown.

**Tasks**
- [x] Add a donation URL setting `DONATION_URL` (empty by default, validated to absolute https links) and pass it to the template
- [x] Add the donation line under the results and in the footer when the setting is present
- [x] Add the Open-Meteo attribution link (with the CC BY 4.0 licence link) to the footer, always shown
- [x] Add OpenStreetMap credit to the footer (added as a precaution; Nominatim's usage policy was not re-read, so check it)
- [x] Styles in `static/style.css` as classes (no inline styles); footer links are white and underlined over the photo
- [x] Layout checked in a real browser: with the link and credits the page needs 753px of height. It fits the 768px reference window with no scrollbar and no sideways overflow at 1366x768 and 1920x1080. At 1280x720 it scrolls by 33px (10px of that is the credits, 23px the donation line).
- [x] Tests: 16 new (URL validation, link absent when empty, present when set, absent on error and empty pages, `rel`/`target`, attribution always present). Offline suite: 110 tests passing.
- [x] Set the donation URL in `render.yaml`, document the setting in `README.md`, `CLAUDE.md` and `DEPLOY.md`
- [ ] Commit these changes (together with the other uncommitted work in the folder) before tagging `v0.8`
- [ ] Confirm the link and the credits on the live site after the `v0.8` release (this replaces the separate `v0.9` release)

## 5. Alert features not yet built

Order follows the ideas document. Tier 1 and 2 need no database and no new
costs. Tier 3 is the step that makes the app a real alert service.

### Tier 1: in-page
- [ ] Headline banner above the list ("Rain likely tomorrow (80%). Bring an umbrella." / "No rain expected for the next 7 days.")
- [x] Hour-by-hour strip for today using Open-Meteo hourly precipitation: 24 bars for the city's local day, colour-coded on the same severity bands as the daily list, with a one-line summary ("Rain likely from about 15:00 to 18:00, up to 83%. Bring an umbrella.")
- [ ] Tab title and favicon change when rain is coming

### Tier 2: browser-side
- [ ] Remember city and threshold in `localStorage`, check on page load
- [ ] Web Notifications while the tab is open
- [ ] Installable PWA: manifest, service worker, icons
- [ ] Calendar export (`.ics`) for rainy days

### Tier 3: server-pushed alerts
Decide first, because it affects hosting and licensing:
- [ ] Choose the channel to start with (suggestion: ntfy.sh or Telegram, because no signup flow is needed)
- [ ] Decide storage: the free Render filesystem is wiped on restart, so subscriptions need external storage
- [ ] Decide the scheduler: GitHub Actions on a schedule (free) rather than inside the sleeping web service
- [ ] Store latitude, longitude and timezone at signup so scheduled runs do not re-geocode
- [ ] Change detection ("tomorrow went from 20% to 75%") instead of fixed-time spam
- [ ] Check Open-Meteo limits: scheduled checks add calls, and limits apply per IP address (shared runner IPs can hit them sooner)
- [ ] Licence check: free alerts are fine under the non-commercial terms; a paid tier is not (needs a paid Open-Meteo plan)

## 6. Housekeeping

- [ ] Add a small health endpoint that returns the app version, so the pipeline's smoke test can confirm the new release is the one answering
- [x] `RainAlert-Ideas-for-Alerting-Users.md` is already tracked in git (it was in the initial commit) and is annotated in place with what has been built, so the remaining question is only whether to keep it as a living design record or retire it once the ideas are done
- [ ] Keep `render.yaml` tag in step with each release (a hook deploy may not update the service's stored default image)
- [ ] Re-read Render's free-tier terms before the site grows; Render describes the free tier as not meant for production
- [ ] Re-check free-tier limits and Action versions every few months (Dependabot covers the Action versions)

## 7. Deferred or out of scope

- Display ads (AdSense) and affiliate links: need an Open-Meteo commercial plan, ad-network approval, a consent tool for EEA/UK/Swiss visitors and policy pages. The ideas doc does not cover this, so the analysis behind the decision above lives in the decision record, not there.
- Paid alert tier or sponsorship: same licence requirement, plus accounts, payments and support.
- Cloud Run hosting: set aside because of the card requirement and custom-domain costs.

## 8. Open questions

1. ~~Is the Docker Hub image already pushed, and is the Render service created?~~ Answered 2026-10-21: neither exists yet. Order of work: Docker Hub repo and token, GitHub secrets, first image (via `v0.8` tag), then the Render Blueprint, then the domain.
2. Does the free Render plan offer a deploy hook for this service?
3. ~~What is the Buy Me a Coffee URL, and what wording do you want?~~ Answered: <https://buymeacoffee.com/rainalert>, wording above.
4. ~~Ship the donation link in `v0.8` or `v0.9`?~~ Answered: `v0.8`. Built and tested.
5. Which alert channel comes first: ntfy.sh, Telegram or email?
