# RainAlert: Ideas for Alerting Users

Oct 21, 2026 · @Vedad

## Where RainAlert stands today

RainAlert is pull-only: users must open it, type a city and read a seven-day list, so nothing in it actually alerts anyone. It is also stateless, with no accounts, database or background jobs, so most real alerting ideas need one small piece of persistence.

The ideas below are grouped by cost: in-page changes first, then browser-side features, then server-pushed notifications.

## Tier 1: In-page alerts (no new infrastructure)

Four changes make the page itself feel like an alert, and all of them stay inside the existing Flask template and CSS.

- **Visual rain severity.** Colour-code each day by `precipitation_probability_max`: grey under 30%, blue at 30-60%, strong blue or amber above 60%. Add an umbrella icon on days over a threshold. This is mostly CSS classes in `style.css` plus one class on each `.weather-item`.
- **Headline banner above the list.** For example "Rain likely tomorrow (80%). Bring an umbrella." or "No rain expected for the next 7 days." It takes a few lines in `fetch_forecast` to find the first day over a threshold, and fits the English-sentence convention.
- **Hour-by-hour strip for today.** Open-Meteo also provides `hourly=precipitation_probability`. A row such as "Rain from about 15:00 to 18:00" is more actionable than a daily maximum, which cannot tell you whether to leave now or in an hour.
- **Tab title and favicon as the alert.** Set the `<title>` to "Rain tomorrow - Rain Alert" and swap the favicon when rain is coming. Anyone who leaves the tab open sees it for free.

## Tier 2: Browser-side alerts (still no backend)

These features keep state in the user's browser, so the server stays stateless.

- **Saved city and threshold in `localStorage`.** "Remember my city" and "Alert me above X%". The page checks automatically on load, so there is no retyping.
- **Web Notifications while the tab is open.** A small JS timer re-fetches every 30 minutes and fires a notification such as "Rain starts in about 1 hour". It is simple, but only works while the tab is open.
- **Installable PWA.** Add a `manifest.json` and a service worker so users can install the app on a phone home screen. True push when the app is closed needs the server-side component in Tier 3.
- **Calendar export (.ics).** An "Add rainy days to my calendar" button that generates an `.ics` file with an event on each day over the threshold. The user's own calendar app does the alerting, with no notification infrastructure on your side.

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

## Suggested build order

Start with the cheap in-page wins, and add real push last, because that step is what makes the name honest.

1. Headline banner and colour-coding (Tier 1).
2. Hour-by-hour "today's rain" strip (Tier 1).
3. Saved city and threshold in `localStorage` (Tier 2).
4. ntfy.sh or Telegram push (Tier 3), which needs only a SQLite table and one scheduled script.

Steps 1 and 2 give an immediate "alert" feel in an afternoon.

## Codebase notes to keep in mind

Two existing design choices in `app.py` affect any scheduled alerting.

- **Dates are in the city's local time.** `CLAUDE.md` documents that `timezone=auto` is deliberate. A scheduled job must respect this when deciding what "tomorrow" or "07:00" means, so store the timezone from Open-Meteo's response with each subscription.
- **The geocoding cache is per process.** The `lru_cache` on `get_coordinates` would not be shared with a separate scheduler. Store latitude and longitude at signup rather than re-geocoding on every run, which also keeps you inside Nominatim's rate limits.
