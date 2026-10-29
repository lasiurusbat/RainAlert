/* RainAlert service worker.
 *
 * The app can be installed on a phone and it opens without a network. Two
 * rules run through all of it:
 *
 *   1. The forecast is never cached. A page that shows yesterday's rain
 *      chance is worse than no page at all, so a navigation goes to the
 *      network first, and the alert poll is never cached at all.
 *   2. The shell is cached, so the app opens offline and shows an honest
 *      offline page instead of the browser's error screen.
 *
 * Bump CACHE_VERSION when the shell changes (style.css, app.js, an icon).
 * The old caches are dropped when the new worker takes over, and the shell
 * is refreshed in the background, so a reader gets the new files on the
 * load after the one that fetched them.
 */
const CACHE_VERSION = 'v19';
const CACHE_NAME = 'rainalert-shell-' + CACHE_VERSION;

/* The shell: the files the page needs to look like Rain Alert. The
 * forecast itself is not in it - the page is rendered by the server, and
 * a cached forecast would be a lie. */
const SHELL = [
    '/static/style.css',
    '/static/app.js',
    '/static/fonts/archivo-latin.woff2',
    '/static/favicon.svg',
    '/static/favicon-rain.svg',
    '/static/icon-180.png',
    '/static/icon-192.png',
    '/static/icon-512.png',
    '/static/icon-maskable-512.png',
    '/static/image/rain-alert-bg.jpg',
    '/static/offline.html'
];

/* The page shown when the network is gone. It says so plainly, and it does
 * not show a stale forecast. */
const OFFLINE_URL = '/static/offline.html';

self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(function (cache) { return cache.addAll(SHELL); })
            .then(function () { return self.skipWaiting(); })
    );
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys()
            .then(function (names) {
                return Promise.all(names.map(function (name) {
                    if (name === CACHE_NAME) { return null; }
                    return caches.delete(name);
                }));
            })
            .then(function () { return self.clients.claim(); })
    );
});

/* A page request: the network first, and the offline page when there is
 * no network. The response is never put in a cache, and the browser's own
 * cache is bypassed as well: a stale rain chance is worse than none. */
function networkFirst(request) {
    return fetch(request, {cache: 'no-store'}).catch(function () {
        return caches.match(OFFLINE_URL).then(function (cached) {
            return cached || Response.error();
        });
    });
}

/* A shell file: the cached copy straight away, and a fresh one fetched in
 * the background for the next load. */
function shellAsset(event, request) {
    var fresh = fetch(request).then(function (response) {
        if (response && response.ok) {
            var copy = response.clone();
            return caches.open(CACHE_NAME)
                .then(function (cache) { return cache.put(request, copy); })
                .then(function () { return response; });
        }
        return response;
    });
    event.waitUntil(fresh.catch(function () { return null; }));
    return caches.match(request).then(function (cached) {
        return cached || fresh;
    });
}

self.addEventListener('fetch', function (event) {
    var request = event.request;
    if (request.method !== 'GET') { return; }

    var url = new URL(request.url);
    if (url.origin !== self.location.origin) { return; }

    /* The alert poll is live data. It is never cached and never served
     * from a cache: a notification about yesterday's rain is wrong. */
    if (url.pathname.indexOf('/api/') === 0) { return; }

    /* The manifest and the worker itself are never served from a cache. */
    if (url.pathname === '/manifest.json'
            || url.pathname === '/service-worker.js') { return; }

    /* The calendar export is live data: it is the forecast as it is at the
     * moment the file is asked for. It is never cached, and it is never
     * replaced by the offline page, which is not a calendar. */
    if (url.pathname === '/calendar.ics') { return; }

    if (request.mode === 'navigate') {
        event.respondWith(networkFirst(request));
        return;
    }

    if (url.pathname.indexOf('/static/') === 0) {
        event.respondWith(shellAsset(event, request));
    }
});
