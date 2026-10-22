"""What each release of Rain Alert brought.

The release notes page is written by hand, in the same way as the API
reference: it describes the app, it is not generated from it. Each entry
is a version and the points that version brought, newest first.

**Cutting a release means adding an entry here.** The version on the top
entry is the one the build stamps into the footer, so the page and the
footer never disagree about which release is running. The number of the
release in preparation is also the fallback tag in `render.yaml`, so the
two are kept together.

The wording follows the app's own rules: the band names are the honest
ones, a probability is never called an intensity, and nothing here
promises a forecast the service does not give.
"""

RELEASES = [
    {
        "version": "0.8",
        "name": "The page is a night street",
        "points": [
            "The panel is a dark plate laid over the photograph, in the "
            "colours of the picture: asphalt, haze, mist, paper and the "
            "amber of a street lamp. Amber is the only accent, so a "
            "colour on the page always means something about the rain.",

            "The answer is at the top. The city is the headline, one "
            "sentence about the week sits under it, and the search is a "
            "compact field in the top bar instead of a form above the "
            "answer.",

            "Every hour's number is written over its own bar, so a value "
            "never needs a hover and a touch screen never shows one. The "
            "current hour is a labelled rule through the strip, drawn in "
            "ink so the data mark itself is not altered.",

            "The week is seven columns of figures. Picking one puts that "
            "day in the panel above the week and draws that day's graph, "
            "so the graph and the panel are always about the same day.",

            "Every city has one address, /city/<slug>, and everything "
            "else is sent there. A city index, a real 404 page and a "
            "sitemap make the site findable, and a missing page answers "
            "404 while a broken upstream answers 503.",
        ],
    },
    {
        "version": "0.7",
        "name": "The rainy days in your own calendar",
        "points": [
            "A quiet link beside \"7-day rain chance\" downloads an "
            "iCalendar file with one all-day event for every day that "
            "reaches the threshold, and your own calendar app does the "
            "reminding.",

            "The file is built on the server, so the rule that decides "
            "which days go into it sits behind the test suite, and the "
            "calendar can never disagree with the list on the page.",

            "Your own threshold is used when you have set one, and the "
            "app's when you have not. The events are all-day, because the "
            "forecast is a daily maximum.",
        ],
    },
    {
        "version": "0.6",
        "name": "An alert while the tab is open, and an app you can install",
        "points": [
            "A bell beside the strip's title turns on browser "
            "notifications. The page polls for news, and the decision "
            "about what is worth interrupting a reader for is made on the "
            "server, not in the browser's script.",

            "The same news is never said twice: every event carries a "
            "key, and the browser remembers the keys it has already "
            "shown.",

            "The app can be added to a home screen. The forecast is never "
            "cached, because a rain chance from yesterday is wrong, and "
            "the shell is, so the app opens without a network and shows "
            "an honest offline page instead of a stale forecast.",
        ],
    },
]
