"""What each release of Rain Alert brought.

The release notes page is written by hand, in the same way as the API
reference: it describes the app, it is not generated from it. Each entry
is a version, the date it was cut, a name for it, and the features it
brought, newest first. The date is the day the tag was pushed, as an ISO
date.

**Cutting a release means adding an entry here.** The version on the top
entry is the number of the release in preparation, and that number is also
the fallback tag in `render.yaml`, so the two are kept together.

The wording follows the app's own rules: the band names are the honest
ones, a probability is never called an intensity, and nothing here
promises a forecast the service does not give.
"""

RELEASES = [
    {
        "version": "1.2.2",
        "date": "2026-10-30",
        "name": "A footer that fits a phone",
        "features": [
            {
                "title": "The footer is tidier",
                "text": "The notice, the data credits and the build are now "
                        "three short lines, centred, on a plate of dark "
                        "glass that lets the photograph show through while "
                        "the words stay readable. The two credits are set "
                        "apart by a thin line, and when the backup weather "
                        "service is in use, the sentence about it starts a "
                        "row of its own instead of leaving one word alone.",
            },
            {
                "title": "Easier to use on a phone",
                "text": "On a narrow screen each credit has a line to "
                        "itself, and \"Release notes\" and \"Install app\" "
                        "are large enough to touch without missing. The "
                        "footer keeps clear of the home bar on an iPhone, "
                        "and its links show a clear outline when reached "
                        "with a keyboard.",
            },
            {
                "title": "A clearer way to say thanks",
                "text": "\"Buy me a coffee\" is now a small light button, "
                        "the one bright shape in the footer, so it is found "
                        "without being pushed. It is still a single link to "
                        "a one-off donation, and the credits to Open-Meteo "
                        "and OpenStreetMap are unchanged.",
            },
        ],
    },
    {
        "version": "1.2.1",
        "date": "2026-10-30",
        "name": "The backup, tried for real",
        "features": [
            {
                "title": "The second service has answered a real request",
                "text": "The backup forecast from OpenWeather, added in "
                        "1.2.0, had been written from its documentation "
                        "alone. It has now been run against the live "
                        "service: the week, the chances and the "
                        "temperatures, and the hours of today and "
                        "tomorrow, all came back as the site expects. "
                        "Nothing on the page changes with this release.",
            },
            {
                "title": "Rain in millimetres is left out rather than guessed",
                "text": "OpenWeather's documentation describes the amount "
                        "of rain as a rate per hour, which a day's total "
                        "cannot be made from. In practice it sent a plain "
                        "figure for at least one day. A figure is shown "
                        "as millimetres; anything else is left out of the "
                        "day's panel rather than worked out from a rate.",
            },
        ],
    },
    {
        "version": "1.2.0",
        "date": "2026-10-29",
        "name": "A second weather service to ask",
        "features": [
            {
                "title": "A backup when the first service says no",
                "text": "The forecast service this site uses for free "
                        "limits how many requests one address may make in "
                        "a day, and the host the site runs on shares that "
                        "address with other apps. On 29.10.2026 the whole "
                        "day's allowance was gone and every forecast "
                        "failed. When that happens, the site now asks a "
                        "second service, OpenWeather, on an allowance of "
                        "its own. The week and the hourly strip look the "
                        "same; the forecast just comes from the other "
                        "service, and the footer says so.",
            },
            {
                "title": "What the backup does not know",
                "text": "OpenWeather does not say how long the rain lasts, "
                        "so that line is left out of a day's panel rather "
                        "than guessed. It reports the hours only about a "
                        "day ahead, so the hourly strip for later days "
                        "says that hourly detail is not available. The "
                        "hours of today that have already gone, or that "
                        "it did not report, are shown as unknown, not as "
                        "dry.",
            },
        ],
    },
    {
        "version": "1.1.5",
        "date": "2026-10-29",
        "name": "Saying why the weather service said no",
        "features": [
            {
                "title": "The refusal is written down",
                "text": "When the forecast service turns a request away, "
                        "the site's log now records what the service said "
                        "- which limit was reached, and how long it asks "
                        "to wait - alongside the status. That tells a "
                        "short burst from an address that has used up its "
                        "allowance, which is what decides how the problem "
                        "is fixed. The page you read still says only that "
                        "the service is unavailable.",
            },
        ],
    },
    {
        "version": "1.1.4",
        "date": "2026-10-29",
        "name": "Fewer questions for the weather service",
        "features": [
            {
                "title": "Forecasts are kept for ten minutes",
                "text": "The forecast service limits how often one address "
                        "may ask it for weather, and the host this site "
                        "runs on shares that address with other apps, so "
                        "at busy times the service refused and the page "
                        "said it was unavailable. The site now keeps each "
                        "forecast it fetched for ten minutes, per place and "
                        "temperature scale, and asks again after that. "
                        "Your browser still never keeps a forecast, and a "
                        "failed answer is never kept, so a retry asks "
                        "again.",
            },
            {
                "title": "A gentler crawl",
                "text": "The robots file now asks crawlers to wait ten "
                        "seconds between requests and shuts out an SEO "
                        "crawler that was fetching city pages one after "
                        "another and bringing no readers, so the visitors "
                        "get the allowance instead.",
            },
        ],
    },
    {
        "version": "1.1.3",
        "date": "2026-10-29",
        "name": "A fresh look at the sky",
        "features": [
            {
                "title": "Refresh the forecast",
                "text": "A small refresh icon now sits beside \"Notify me\" "
                        "above the hourly strip. It loads the forecast "
                        "again for the same city and the same temperature "
                        "scale, so you can check for a change without "
                        "searching again. It is a plain link, so it works "
                        "without JavaScript too.",
            },
            {
                "title": "Failures say why in the log",
                "text": "When the weather or geocoding service cannot be "
                        "reached, the site's log now records the reason "
                        "along with the city, such as a rate limit or a "
                        "timeout, so a fault can be found instead of "
                        "guessed at. You still see only the plain "
                        "\"unavailable right now\" message on the page.",
            },
        ],
    },
    {
        "version": "1.1.2",
        "date": "2026-10-23",
        "name": "Found by the search engines",
        "features": [
            {
                "title": "Verified with Google and Bing",
                "text": "The site now answers the ownership checks of "
                        "Google Search Console and Bing Webmaster Tools, "
                        "each with a small file at the root of the site. "
                        "That is what lets the sitemap be submitted to "
                        "both, so the pages of the site can be found in "
                        "their results. Nothing on the pages you read has "
                        "changed.",
            },
        ],
    },
    {
        "version": "1.1.1",
        "date": "2026-10-23",
        "name": "A tighter lock on the door",
        "features": [
            {
                "title": "Security headers on every page",
                "text": "Every response now carries the headers browsers "
                        "use to protect a reader: a strict content security "
                        "policy, HTTPS-only transport, no framing of the "
                        "site inside another page, no guessing of file "
                        "types, a trimmed referrer and a permissions policy "
                        "that switches off the camera, microphone and "
                        "location. The site loads nothing from anyone "
                        "else, so the policy allows nothing from anyone "
                        "else.",
            },
        ],
    },
    {
        "version": "1.1.0",
        "date": "2026-10-23",
        "name": "Put it on your home screen",
        "features": [
            {
                "title": "An Install app link in the footer",
                "text": "The app could always be installed, and now the page "
                        "says so. When your browser can install it, the "
                        "footer offers Install app: on Chrome for Android it "
                        "opens the browser's own install dialog, and on "
                        "Safari for iPhone it shows the two taps that do "
                        "it. A browser that cannot install the app, or an "
                        "app that is already installed, never sees the "
                        "link.",
            },
            {
                "title": "A hint, once, when you come back",
                "text": "If you return to a city you asked the app to "
                        "remember, a small note offers to put Rain Alert on "
                        "your home screen. It is shown once and never on "
                        "your first visit, and it sits over the page "
                        "instead of pushing it about. Not now closes it for "
                        "good.",
            },
            {
                "title": "A page that fits a phone's screen",
                "text": "On some Android phones the page could be dragged a "
                        "little further than its own content, because the "
                        "browser counted the height of its toolbars as part "
                        "of the screen. The page now uses the height that is "
                        "really visible, so it fits the screen and stays "
                        "put.",
            },
        ],
    },
    {
        "version": "1.0.1",
        "date": "2026-10-22",
        "name": "A page that is not there says so",
        "features": [
            {
                "title": "A missing page no longer promises a forecast",
                "text": "A city the geocoder does not know has no page, and "
                        "the page now says so in its title, its description "
                        "and its address - the same words the site's own 404 "
                        "page uses - instead of promising a 7-day rain "
                        "chance for a place that is not there. A shared link "
                        "to a city that does not exist no longer shows a "
                        "forecast in the tab.",
            },
        ],
    },
    {
        "version": "1.0",
        "date": "2026-10-22",
        "name": "The 7-day rain chance for any city",
        "features": [
            {
                "title": "A forecast for any city",
                "text": "Type a city name. It is geocoded with Nominatim "
                        "and the week comes from Open-Meteo. There is no "
                        "account, no API key and no database, so there is "
                        "nothing to sign up for and nothing that tracks "
                        "you.",
            },
            {
                "title": "Seven days, three honest words",
                "text": "Each day is banded as Rain unlikely, Rain possible "
                        "or Rain likely. A chance of rain is never dressed "
                        "up as an amount of rain, and a day the service did "
                        "not report is named as such instead of being "
                        "counted as a dry one.",
            },
            {
                "title": "The hour by hour, for the day you pick",
                "text": "Every hour's chance is written over its own bar, "
                        "so a value never needs a hover, and the current "
                        "hour is a labelled rule through the strip. Picking "
                        "a day in the week redraws the graph for that day, "
                        "with that day's own summary.",
            },
            {
                "title": "The umbrella answer, and where it came from",
                "text": "The banner under the city's name, the tab title "
                        "and the tab icon are one alert, decided by the "
                        "same threshold: the first day worth mentioning. "
                        "Today's figure comes from the hours that are left "
                        "rather than from the whole day, so at six in the "
                        "evening the morning's downpour is not counted "
                        "against you.",
            },
            {
                "title": "Your own threshold, kept in your browser",
                "text": "Set the chance that matters to you and the days "
                        "that reach it are marked with your own triangle, "
                        "apart from the app's umbrella: your limit and the "
                        "app's advice are two different answers. Your "
                        "threshold and your city live in the browser, and "
                        "the server never sees either of them.",
            },
            {
                "title": "A notification while the tab is open",
                "text": "The page asks the server whether there is anything "
                        "worth interrupting you for - rain in this hour, or "
                        "rain starting within the next two - and the server "
                        "is the one that decides. The same news is never "
                        "said twice, and the browser's own permission is "
                        "asked for before anything is shown.",
            },
            {
                "title": "The wet days in your own calendar",
                "text": "One click downloads an iCalendar file with one "
                        "all-day event for every day that reaches the "
                        "threshold, and your own calendar app does the "
                        "reminding. The file is built on the server from "
                        "the same numbers the page shows, so the calendar "
                        "and the list cannot disagree.",
            },
            {
                "title": "One address per city",
                "text": "Every city has one page, at /city/<slug>, and "
                        "every other way of asking for the same forecast is "
                        "sent there. There is a city index and a sitemap "
                        "for the search engines, a missing page answers "
                        "404 and a broken upstream answers 503.",
            },
            {
                "title": "Installable, and honest when it cannot reach the "
                         "network",
                "text": "The app can be added to a home screen. The forecast "
                        "is never cached, because a rain chance from "
                        "yesterday is wrong; the shell is, so the app opens "
                        "without a network and shows an offline page that "
                        "says plainly that it has no forecast for you.",
            },
            {
                "title": "Celsius or Fahrenheit",
                "text": "The weather service converts the temperatures, not "
                        "the app, so the number on the page is the "
                        "service's own and the two can never round "
                        "differently. Your scale travels with the address, "
                        "so a link you send keeps it.",
            },
            {
                "title": "One street at night",
                "text": "The panel is a dark plate over a photograph of a "
                        "night street, in the colours of the picture. Amber "
                        "is the only accent, so a colour on the page always "
                        "means something about the rain, and the type is "
                        "self-hosted, so the page asks no third party for "
                        "anything.",
            },
        ],
    },
]
