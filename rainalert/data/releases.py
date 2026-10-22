"""What each release of Rain Alert brought.

The release notes page is written by hand, in the same way as the API
reference: it describes the app, it is not generated from it. Each entry
is a version, a name for it, and the features it brought, newest first.

**Cutting a release means adding an entry here.** The version on the top
entry is the number of the release in preparation, and that number is also
the fallback tag in `render.yaml`, so the two are kept together.

The wording follows the app's own rules: the band names are the honest
ones, a probability is never called an intensity, and nothing here
promises a forecast the service does not give.
"""

RELEASES = [
    {
        "version": "1.0",
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
