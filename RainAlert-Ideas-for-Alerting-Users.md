# RainAlert: Ideas for Alerting Users

Oct 21, 2026 · @Vedad

*Status annotations added 2026-10-21. The prose below is the original proposal and is kept as written; each idea carries a note on what was actually built, so the document stays a record of both the thinking and the result. ✅ means built, ⬜ means not built yet.*

*Design annotations added 2026-10-22. The page was rebuilt in the "night street" direction afterwards: the card became a dark panel over the photograph, the week became seven columns of figures, the city name became the heading, and the type became a self-hosted Archivo. Three details below therefore describe the page as it was when they were written and not as it is now: the current hour is a **labelled rule** rather than a pulsing dot, the rain favicon is the umbrella on the amber plate rather than an amber square against a blue cloud, and the week is a row of columns rather than a list of tinted rows. The design itself is described in `CLAUDE.md`.*

## Where RainAlert stands today

RainAlert is pull-only: users must open it, type a city and read a seven-day list, so nothing in it actually alerts anyone. It is also stateless, with no accounts, database or background jobs, so most real alerting ideas need one small piece of persistence.

**One thing to keep in mind while reading this document: the app is not deployed.** As of 2026-10-21 there is no release tag, no image on Docker Hub, and `rainalert.live` does not serve RainAlert — it runs locally, from `python app.py` or `docker compose up`. So "pull-only" currently means "pull-only by a developer on their own machine", and there are no users to alert at all. Every tier below is a design that has to survive being put online first, not a feature waiting for a user. The deployment steps are in `DEPLOY.md`.

The ideas below are grouped by cost: in-page changes first, then browser-side features, then server-pushed notifications.

**Where it stands now:** all four Tier 1 ideas are built — the page colour-codes rain risk, shows an hour-by-hour strip for today with a "bring an umbrella" summary, leads with a one-line headline about the week, and renames the browser tab and swaps the favicon when rain is coming. Three Tier 2 ideas are built too: the reader's city and their own rain threshold live in the browser's `localStorage`, and the server stays stateless; a browser notification says so when rain is about to start while the tab is open; and the app is installable, with a manifest, a service worker and its own icons, so it can live on a home screen and open without a network. The app is still pull-only in the sense that matters here: nothing reaches a user who is not already looking at the page — and nothing reaches anyone at all until it is deployed — and there is still no database, account or background job.

## Tier 1: In-page alerts (no new infrastructure)

Four changes make the page itself feel like an alert, and all of them stay inside the existing Flask template and CSS.

- **Visual rain severity.** Colour-code each day by `precipitation_probability_max`: grey under 30%, blue at 30-60%, strong blue or amber above 60%. Add an umbrella icon on days over a threshold. This is mostly CSS classes in `style.css` plus one class on each `.weather-item`.
  - ✅ **Built.** Three bands — *rain unlikely* / *rain possible* / *rain likely* — plus a separate *unknown* band, because a missing value is not the same as a 0% chance. Grey, blue and amber as proposed, with the band names carried in a legend above the list and in a screen-reader-only span on each row, so severity is never colour alone. Tinted rows, a left border and a dot per day. The umbrella icon appears at the `UMBRELLA_THRESHOLD` (50%), and the thresholds are environment variables.
- **Headline banner above the list.** For example "Rain likely tomorrow (80%). Bring an umbrella." or "No rain expected for the next 7 days." It takes a few lines in `fetch_forecast` to find the first day over a threshold, and fits the English-sentence convention.
  - ✅ **Built.** One line above the list, in `forecast_headline()`. It names the first day worth mentioning — a day at or above the umbrella threshold, a day that is only *possible*, or the week as a whole when no day is. The band name in the sentence is the day's own band, the same one its row in the list carries, so the banner and the list never disagree; the colour follows the band and the band name is in the text, so the meaning never rests on the colour alone.
    - **Today is judged on the hours that are left.** The daily maximum covers the whole day, so at 18:00 it still counts the morning's downpour while the reader can only walk into the evening. Today's figure in the banner comes from the remaining hours and says so — "Rain likely for the rest of today (80%)" — while its row keeps the daily maximum. The two are different quantities and each is labelled with which one it is.
    - When the day is over it drops out of the banner entirely, and a missing chance is never counted as dry: a quiet week with one unreported day is "most of", not "all of".
- **Hour-by-hour strip for today.** Open-Meteo also provides `hourly=precipitation_probability`. A row such as "Rain from about 15:00 to 18:00" is more actionable than a daily maximum, which cannot tell you whether to leave now or in an hour.
  - ✅ **Built.** 24 bars for the city's local day, coloured on the same severity bands as the daily list, with the bar height giving the chance. It comes from `hourly=precipitation_probability` in the *same* request as the daily fields, so the page still makes one upstream call, not two.
    - The summary is one line, in the sentence convention above: "Rain likely from about 15:00 to 18:00, up to 83%. Bring an umbrella." It uses the umbrella threshold, so it agrees with the ☔ icon on the daily list, and it only looks at hours that have not happened yet.
    - The current hour is marked with a **pulsing dot** under the baseline, taken from the `current` block the API returns in the same local time. The pulse is decoration and is dropped under `prefers-reduced-motion: reduce`; the dot stays, so the hour is still marked.
    - Bar heights are bucketed into 5% steps so they can live in the stylesheet as classes. The exact percentage is in the tooltip and in a table view below the strip, so the rounding never hides a value and nothing is reachable only by hovering.
    - The hours are the **city's** local hours, never the viewer's — the same rule the daily dates follow.
- **Tab title and favicon as the alert.** Set the `<title>` to "Rain tomorrow - Rain Alert" and swap the favicon when rain is coming. Anyone who leaves the tab open sees it for free.
  - ✅ **Built.** The title becomes "Rain tomorrow - Rain Alert" and the favicon swaps to an amber rain icon, decided by `tab_alert()` in `app.py`.
    - It fires at the **same `UMBRELLA_THRESHOLD`** as the ☔ icon and the banner's "Bring an umbrella", so the tab, the banner and the row can never disagree about whether rain is worth noticing.
    - The title names the day — "today", "tomorrow", or the weekday beyond that — rather than the date, because a tab title is read at a glance.
    - Today is judged on the **hours that are left**, exactly as the banner judges it, so the title does not still say "Rain today" at 18:00 when the morning's downpour has been and gone. A day that is over drops out and the next wet day is named instead. A missing chance is never counted as dry, so an unreported week simply has no alert.
    - The two icons are **separate files** (`favicon.svg` and `favicon-rain.svg`), because browsers cache a favicon by its URL and one recoloured file would keep showing the old icon until the cache was cleared. The rain icon changes **shape** as well as colour — an amber square with white streaks against a blue cloud — so the two are told apart at 16 pixels by the shape and not the hue alone.

## Tier 2: Browser-side alerts (still no backend)

These features keep state in the user's browser, so the server stays stateless.

- **Saved city and threshold in `localStorage`.** "Remember my city" and "Alert me above X%". The page checks automatically on load, so there is no retyping.
  - ✅ **Built.** Both preferences live in the browser's `localStorage`, in `static/app.js`. The server never sees either one and stays stateless.
    - A city is only remembered **once a search for it has actually worked**: the submitted city waits in `sessionStorage` until the result page confirms the search was good. A typo is never remembered, and a failed search does not destroy the city that was already saved.
    - The start page loads the remembered city by itself, so there is no retyping. A page that already shows a forecast is left alone — reloading it would throw the reader's forecast away.
    - The threshold is marked with **its own symbol and its own words** (a ▲), because it answers a different question from the umbrella. The umbrella, the banner, the ☔ icon and the tab title are the app's advice and all fire at the same `UMBRELLA_THRESHOLD`; the reader's own limit is a second, separate answer, and the two never stand in for each other.
    - The threshold is compared against the number the page shows, so the marker and the percentage can never disagree. A day the service did not report is never counted as a dry day, and never marked as a wet one either.
    - Without JavaScript the preferences row is hidden and the page is exactly what it was before. The server tells the page what kind of page it is through three attributes on `<body>`: `data-autoload`, `data-search` and `data-city`.
    - One limitation to carry into Tier 3: `localStorage` follows the **browser**, not the person. A reader who switches device, or opens the site in a private window, gets a blank slate — the saved city does not follow them. That is the same gap Tier 3's server-side table would close, and it is the strongest argument for having one.
- **Web Notifications while the tab is open.** A small JS timer re-fetches every 30 minutes and fires a notification such as "Rain starts in about 1 hour". It is simple, but only works while the tab is open.
  - ✅ **Built.** A 🔔 button next to the hourly strip's title turns the notifications on, and the page polls the server every 30 minutes while it is open.
    - The **rule is on the server**: `notification_event()` in `rainalert/domain/alerts.py` decides what is worth interrupting a reader for — rain in the current hour, or rain starting within the next two hours — and writes the wording. The browser asks `/api/alert` and shows what comes back, so the decision is behind the offline test suite rather than inside a string in `app.js`.
    - **The same news is never said twice.** Each event carries a key, and the browser remembers the keys it has shown: a poll that lands twice in the same wet hour, or two tabs open at once, do not repeat it.
    - The **reader's own threshold** is used when they have set one, and the notification says so ("Above your 40% threshold."). Without one it uses the app's umbrella threshold, and then it is the app's advice, umbrella and all — the same split as the ▲ marker, for the same reason.
    - It says **when**, not how long: "Rain likely from 15:00", with the city's own local hour, exactly like the strip above it.
    - The limit is the browser's, and the page does not pretend otherwise: it only works while the tab is open, the Notification API only exists in a secure context, and a browser that has blocked notifications says "Notifications blocked" instead of offering a button that cannot work.
- **Installable PWA.** Add a `manifest.json` and a service worker so users can install the app on a phone home screen. True push when the app is closed needs the server-side component in Tier 3.
  - ✅ **Built.** `static/manifest.json` and `static/service-worker.js`, served from the **root** (`/manifest.json` and `/service-worker.js`) so the scope covers the whole site, with four generated PNG icons (180, 192, 512 and a maskable 512 for Android) and an `apple-touch-icon` for iOS. The installed app opens in its own window with no browser chrome.
    - **The forecast is never cached.** A navigation goes to the network first and bypasses the browser's own cache as well, the alert poll is never intercepted, and `/` is deliberately absent from the shell list — there is a test that asserts it. A rain chance from yesterday is wrong, so it is never replayed.
    - **The shell is cached**, so the app opens without a network and shows a short offline page saying that the forecast cannot be fetched — not a stale forecast. The shell is the stylesheet, the script, the icons and the background photo: the files that make the page *look* like Rain Alert, and nothing that carries data.
    - **It still cannot reach a closed app.** The service worker caches files; it cannot wake the app and deliver a notification. That is the same Tier 3 gap as the browser notification, and the offline page is the honest face of it.
- **Calendar export (.ics).** An "Add rainy days to my calendar" button that generates an `.ics` file with an event on each day over the threshold. The user's own calendar app does the alerting, with no notification infrastructure on your side.
  - ✅ **Built.** A quiet "📅 Add rainy days to my calendar" link on the caption line beside "7-day rain chance" downloads a standard iCalendar file from `/calendar.ics`, with one all-day event for every day that reaches the threshold.
    - **The file is built on the server**, by `build_calendar()` in `rainalert/calendar_ics.py`, so the rule that decides which days go into it is behind the offline test suite. The browser's part is narrow: it says which threshold the reader is using, and it takes the link away when nothing reaches it — a link that would download an empty calendar is not an offer.
    - **The reader's own threshold is used when they have set one**, and the event says so ("At or above your 40% alert threshold."). Without one it uses the app's umbrella threshold, and then it is the app's advice, umbrella and all — the same split as the ▲ marker and the notification, for the same reason.
    - **The events are all-day events**, because the forecast is a daily maximum: the file says which days are wet, and the reader's own calendar app decides when to remind them about it. The event id is derived from the city and the date, so importing the file again updates the same events instead of adding a second copy of every one of them.
    - **A day the service did not report is never in the file.** An unknown chance is not a chance of anything, so it is never counted as a wet day — and never as a dry one either.
    - **This is the one alert that needs nothing from the app at all.** Once the file is in a calendar, the reminder comes from the calendar app: no tab to keep open, no server to keep running, no phone app to install. It is the whole of Tier 3 handed to software the reader already has.

The saved city, the threshold, the browser notification, the installable PWA and the calendar export are built. Tier 2 is finished.

## Tier 3: Server-pushed alerts (needs persistence and a scheduler)

This is where the app becomes a real alert service. It needs a small SQLite table (city, lat/lon, threshold, contact method, last-notified) and a scheduled job, such as APScheduler, cron, or a GitHub Actions or GitLab CI schedule.

**Delivery channels**

- **Email.** A "Notify me" form with a morning digest at 07:00 local time, for example "Rain expected at 14:00 today (85%)." Use plain SMTP or a free-tier provider.
- **Telegram bot or ntfy.sh.** Probably the lowest-friction route to real phone notifications. ntfy.sh needs no signup: you POST to a topic URL and users subscribe in its app. Telegram's Bot API is also a single HTTP call.
- **Web Push (VAPID).** Free and native on Android and desktop browsers, and on iOS for installed PWAs. It pairs well with the PWA idea in Tier 2.
- **Webhooks (Slack, Discord, Home Assistant).** One URL field per user, which is very easy to implement.

**Smart triggers instead of fixed times**

- **Change detection.** Notify only when the forecast flips, such as "Tomorrow went from 20% to 75%". This avoids notification fatigue.
- **Lead time.** "Notify me 60 minutes before rain", using Open-Meteo's `minutely_15` precipitation data.
- **Quiet hours and commute windows.** Only alert about rain between 07:00-09:00 or 16:00-18:00.

None of these are built yet, and Tier 3 is the step that decides whether the app is worth calling an alert service.

## Suggested build order

Start with the cheap in-page wins, and add real push last, because that step is what makes the name honest.

0. **Put the app online.** — ⬜ **Not started.** Nothing below can alert a user who cannot reach the page. This is a release tag, a Docker Hub image, a Render service and the domain's DNS — no code, but it is ahead of every other item here.
1. Headline banner and colour-coding (Tier 1). — ✅ **Done.**
2. Hour-by-hour "today's rain" strip (Tier 1). — ✅ **Done.**
3. Tab title and favicon as the alert (Tier 1). — ✅ **Done.**
4. Saved city and threshold in `localStorage` (Tier 2). — ✅ **Done.**
5. Web notifications while the tab is open (Tier 2). — ✅ **Done.**
6. Installable PWA (Tier 2). — ✅ **Done.**
7. Calendar export (`.ics`) for rainy days (Tier 2). — ✅ **Done.**
8. ntfy.sh or Telegram push (Tier 3), which needs only a SQLite table and one scheduled script. — ⬜ **Not started.**

Steps 1 to 3 give an immediate "alert" feel in an afternoon, and together they
finish Tier 1. Step 4 is the first Tier 2 feature: it is the one that makes
the app remember you, and it needs no backend at all. Step 5 is the second
half of Tier 2: the tab now says something even when the reader is looking at
something else, which is as far as a browser can go on its own. Step 6
finishes what a browser can do by itself: the app lives on a home screen and
opens without a network. Step 7 is the last Tier 2 piece, and the cheapest of
them all — it hands the alerting to the reader's own calendar app, so it works
with the tab closed and needs no server of ours. Step 0 was not in the
original list, because the app was assumed to be up; it is now first, and
step 8 is not worth building until there is a site to push to — a tab that
is open can talk to the server, and a tab that is closed cannot.

## Codebase notes to keep in mind

Two existing design choices in the app affect any scheduled alerting.

- **Dates are in the city's local time.** `CLAUDE.md` documents that `timezone=auto` is deliberate. A scheduled job must respect this when deciding what "tomorrow" or "07:00" means, so store the timezone from Open-Meteo's response with each subscription.
- **The geocoding cache is per process.** The `lru_cache` on `get_coordinates` would not be shared with a separate scheduler. Store latitude and longitude at signup rather than re-geocoding on every run, which also keeps you inside Nominatim's rate limits.

Both points carry straight over to the hourly strip, which is why its hours are the city's local hours and why "today" follows the current time rather than the first daily entry.
