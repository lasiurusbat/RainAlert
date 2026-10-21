/* RainAlert: the browser-side half of the app.
 *
 * Two preferences live in the browser's localStorage: the city to remember
 * and the personal rain threshold. The server knows nothing about either -
 * it stays stateless, and a first-time visitor sees exactly the page a
 * returning one does.
 *
 * Everything here is progressive enhancement. Without JavaScript the page
 * still works exactly as before; it just does not remember anything, so the
 * preferences row stays hidden.
 */
(function () {
    "use strict";

    var CITY_KEY = "rainalert.city";
    var THRESHOLD_KEY = "rainalert.threshold";
    var PENDING_KEY = "rainalert.pendingCity";

    /* A city name is a short phrase, not a paragraph. The cap keeps a
     * hand-edited or stale value from turning into an absurd URL. */
    var MAX_CITY_LENGTH = 120;
    var LABEL_CITY_LENGTH = 22;

    /* --- Storage ------------------------------------------------------------
     * A browser in private mode, or one where the reader has blocked site
     * data, throws on the first access to localStorage. Every access goes
     * through these helpers, so a browser that refuses to store anything
     * loses the feature instead of breaking the page.
     */
    function safeStorage(getter) {
        try {
            return getter() || null;
        } catch (error) {
            return null;
        }
    }

    function localStore() {
        return safeStorage(function () { return window.localStorage; });
    }

    function sessionStore() {
        return safeStorage(function () { return window.sessionStorage; });
    }

    function read(place, key) {
        if (!place) { return null; }
        try {
            return place.getItem(key);
        } catch (error) {
            return null;
        }
    }

    function write(place, key, value) {
        if (!place) { return; }
        try {
            place.setItem(key, value);
        } catch (error) {
            /* Full or blocked: the feature is simply not available. */
        }
    }

    function remove(place, key) {
        if (!place) { return; }
        try {
            place.removeItem(key);
        } catch (error) {
            /* Nothing to do. */
        }
    }

    /* --- The saved values --------------------------------------------------- */
    function savedCity() {
        var city = (read(localStore(), CITY_KEY) || "").trim();
        return city ? city.slice(0, MAX_CITY_LENGTH) : "";
    }

    function saveCity(city) {
        var trimmed = (city || "").trim();
        if (trimmed) {
            write(localStore(), CITY_KEY, trimmed.slice(0, MAX_CITY_LENGTH));
        } else {
            remove(localStore(), CITY_KEY);
        }
    }

    function savedThreshold() {
        var raw = read(localStore(), THRESHOLD_KEY);
        if (raw === null || raw === "") { return null; }
        var value = parseInt(raw, 10);
        if (isNaN(value)) { return null; }
        return clampThreshold(value);
    }

    function clampThreshold(value) {
        return Math.max(0, Math.min(100, value));
    }

    /* --- The page ------------------------------------------------------------ */
    var body = document.body;
    var rememberBox = document.getElementById("remember-city");
    var rememberLabel = document.getElementById("remember-label");
    var thresholdInput = document.getElementById("alert-threshold");
    var status = document.getElementById("alert-status");
    var form = document.querySelector("form");
    var cityInput = form ? form.querySelector("input[name='city']") : null;
    var calendarLink = document.getElementById("calendar-export");

    /* --- Remembering a city --------------------------------------------------
     * A city is only remembered once a search for it has actually worked. The
     * submitted city waits in sessionStorage until the result page says the
     * search was good, so a typo is never remembered and an old saved city
     * survives a failed search.
     */
    function promotePendingCity() {
        var place = sessionStore();
        var pending = (read(place, PENDING_KEY) || "").trim();
        if (!pending) { return; }

        var searched = (body.getAttribute("data-city") || "").trim();
        var searchStatus = body.getAttribute("data-search");

        if (searchStatus === "error") {
            /* The search failed, so there is nothing worth remembering. */
            remove(place, PENDING_KEY);
            return;
        }
        if (searchStatus === "ok" && pending === searched) {
            saveCity(pending);
            remove(place, PENDING_KEY);
        }
        /* Any other outcome leaves the pending city alone: it may belong to
         * another tab whose search is still on its way. */
    }

    function updateRememberLabel(city) {
        if (!rememberLabel) { return; }
        if (!city) {
            rememberLabel.textContent = "Remember this city";
            rememberLabel.removeAttribute("title");
            return;
        }
        var short = city.length > LABEL_CITY_LENGTH
            ? city.slice(0, LABEL_CITY_LENGTH) + "…"
            : city;
        rememberLabel.textContent = "Remember " + short;
        rememberLabel.setAttribute("title", "Rain Alert opens " + city + " by itself next time.");
    }

    /* --- The personal threshold ----------------------------------------------
     * A day is marked when its rain chance reaches the reader's own
     * threshold. The threshold is the reader's, so it is marked with its own
     * symbol and its own words: the umbrella, the banner and the tab title
     * keep the app's own threshold, and this adds a second, clearly
     * separate answer to a different question.
     */
    function rowChance(row) {
        var raw = row.getAttribute("data-chance");
        if (raw === null || raw === "") { return null; }
        var value = parseFloat(raw);
        return isNaN(value) ? null : value;
    }

    function clearMark(row) {
        var marks = row.querySelectorAll(".alert-marker, .alert-marker-text");
        for (var index = 0; index < marks.length; index += 1) {
            marks[index].parentNode.removeChild(marks[index]);
        }
    }

    function markRow(row, threshold) {
        var date = row.querySelector(".date");
        if (!date) { return; }

        var words = "Above your " + threshold + "% alert threshold.";
        var marker = document.createElement("span");
        marker.className = "alert-marker";
        marker.setAttribute("aria-hidden", "true");
        marker.setAttribute("title", words);
        marker.textContent = "▲";

        var spoken = document.createElement("span");
        spoken.className = "sr-only alert-marker-text";
        spoken.textContent = words;

        /* The marker goes after the date and before the row's screen-reader
         * text, so a reader hears the date, the marker and then the band. */
        var hidden = date.querySelector(".sr-only");
        if (hidden) {
            date.insertBefore(marker, hidden);
            date.insertBefore(spoken, hidden);
        } else {
            date.appendChild(marker);
            date.appendChild(spoken);
        }
    }

    function applyThreshold(threshold) {
        var rows = document.querySelectorAll(".weather-item");
        var above = 0;
        var known = 0;
        var unknown = 0;

        for (var index = 0; index < rows.length; index += 1) {
            var row = rows[index];
            clearMark(row);
            var chance = rowChance(row);
            if (chance === null) {
                /* A day the service did not report is neither above the
                 * threshold nor below it. */
                unknown += 1;
                continue;
            }
            known += 1;
            if (threshold !== null && chance >= threshold) {
                above += 1;
                markRow(row, threshold);
            }
        }
        return { above: above, known: known, unknown: unknown };
    }

    function updateStatus(threshold, counts) {
        if (!status) { return; }
        if (threshold === null) {
            status.textContent = "";
            return;
        }
        if (!counts.known) {
            status.textContent = "Saved.";
            return;
        }
        var text = counts.above === 1
            ? "1 day above " + threshold + "%"
            : counts.above + " days above " + threshold + "%";
        if (counts.unknown === 1) {
            text += " · 1 day unknown";
        } else if (counts.unknown > 1) {
            text += " · " + counts.unknown + " days unknown";
        }
        status.textContent = text;
    }

    /* --- The calendar export -------------------------------------------------
     * A link that puts the rainy days into the reader's own calendar. The
     * file itself is built on the server, so the rule that decides which
     * days go into it lives there, behind the offline test suite. The
     * browser's part is narrow: it says which threshold the reader is
     * using, and it keeps the link away when there is nothing to export.
     *
     * The threshold in the link is the reader's own when they have set one,
     * and the app's own when they have not - the same split the
     * notifications use, for the same reason.
     */
    function updateCalendarLink(threshold, counts) {
        if (!calendarLink) { return; }

        var url = new URL(calendarLink.getAttribute("href"), window.location.href);
        url.searchParams.delete("threshold");
        if (threshold !== null) {
            url.searchParams.set("threshold", String(threshold));
        }
        calendarLink.setAttribute("href", url.pathname + url.search);

        if (threshold === null) {
            /* Without a threshold of the reader's own, the export is the
             * app's own advice, and the server has already worked out
             * whether there is anything to put in it. */
            var appDays = parseInt(calendarLink.getAttribute("data-app-days"), 10);
            calendarLink.hidden = !appDays;
            return;
        }

        /* With the reader's own threshold, the link is only worth offering
         * when a day actually reaches it. */
        calendarLink.hidden = counts.above === 0;
    }

    function refresh() {
        var threshold = savedThreshold();
        if (thresholdInput && document.activeElement !== thresholdInput) {
            thresholdInput.value = threshold === null ? "" : String(threshold);
        }
        var counts = applyThreshold(threshold);
        updateStatus(threshold, counts);
        updateCalendarLink(threshold, counts);
    }

    /* --- Wiring -------------------------------------------------------------- */
    function onThresholdInput() {
        var raw = (thresholdInput.value || "").trim();
        if (raw === "") {
            /* An empty threshold means no threshold: every day would be
             * above it, which is not an alert. */
            remove(localStore(), THRESHOLD_KEY);
            refresh();
            return;
        }
        var value = parseInt(raw, 10);
        if (isNaN(value)) { return; }
        write(localStore(), THRESHOLD_KEY, String(clampThreshold(value)));
        refresh();
    }

    function onThresholdChange() {
        /* The field is corrected here, and not while the number is still
         * being typed, so the reader is not fighting the field mid-word. */
        var threshold = savedThreshold();
        if (thresholdInput) {
            thresholdInput.value = threshold === null ? "" : String(threshold);
        }
        refresh();
    }

    function onRememberChange() {
        if (rememberBox && !rememberBox.checked) {
            /* Untick the box and the city is forgotten straight away. */
            saveCity("");
            remove(sessionStore(), PENDING_KEY);
        }
        updateRememberLabel(savedCity());
    }

    function onSubmit() {
        var city = cityInput ? (cityInput.value || "").trim() : "";
        if (rememberBox && rememberBox.checked && city) {
            write(sessionStore(), PENDING_KEY, city.slice(0, MAX_CITY_LENGTH));
        } else {
            remove(sessionStore(), PENDING_KEY);
            if (rememberBox && !rememberBox.checked) {
                saveCity("");
            }
        }
    }

    /* --- Notifications ------------------------------------------------------
     * Tier 2: a notification while the tab is open. The page polls the
     * server for something worth saying and shows it as a browser
     * notification.
     *
     * What is worth saying is decided on the server, in app.py, so it is
     * one rule with tests behind it rather than a string in this script.
     * The browser's part is narrow: ask for permission, poll, and show
     * what comes back.
     */
    var NOTIFY_ON_KEY = "rainalert.notify.on";
    var NOTIFY_SEEN_KEY = "rainalert.notify.seen";

    /* The keys of the events already shown are kept, so the same news is
     * not announced twice. There is at most one event per check, and the
     * oldest keys are dropped once the list grows. */
    var MAX_SEEN_KEYS = 40;

    /* How often to poll, in minutes. The server says how often it wants
     * to be asked; this is the value used until the first answer. */
    var DEFAULT_POLL_MINUTES = 30;
    var pollMinutes = DEFAULT_POLL_MINUTES;
    var notifyTimer = null;

    var notifyButton = document.getElementById("notify-toggle");
    var notifyIcon = notifyButton
        ? notifyButton.querySelector(".notify-icon") : null;
    var notifyText = notifyButton
        ? notifyButton.querySelector(".notify-text") : null;

    function notificationsSupported() {
        /* The Notification API only exists in a secure context, which
         * means HTTPS or localhost. On plain HTTP there is nothing to
         * offer the reader, so the button stays away. */
        if (window.isSecureContext === false) { return false; }
        return typeof window.Notification === "function";
    }

    function notifyEnabled() {
        return read(localStore(), NOTIFY_ON_KEY) === "1";
    }

    function setNotifyEnabled(enabled) {
        if (enabled) {
            write(localStore(), NOTIFY_ON_KEY, "1");
        } else {
            remove(localStore(), NOTIFY_ON_KEY);
        }
    }

    function seenKeys() {
        var raw = read(localStore(), NOTIFY_SEEN_KEY);
        if (!raw) { return []; }
        try {
            var parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
            return [];
        }
    }

    function rememberKey(key) {
        var keys = seenKeys();
        if (keys.indexOf(key) !== -1) { return; }
        keys.push(key);
        while (keys.length > MAX_SEEN_KEYS) { keys.shift(); }
        write(localStore(), NOTIFY_SEEN_KEY, JSON.stringify(keys));
    }

    function currentCity() {
        var searched = (body.getAttribute("data-city") || "").trim();
        if (searched) { return searched; }
        return savedCity();
    }

    function setNotifyLabel(icon, text) {
        if (notifyIcon) { notifyIcon.textContent = icon; }
        if (notifyText) { notifyText.textContent = text; }
    }

    function updateNotifyButton() {
        if (!notifyButton) { return; }
        if (!notificationsSupported()) {
            /* The browser cannot show notifications, so there is no
             * button to offer. */
            notifyButton.hidden = true;
            return;
        }
        notifyButton.hidden = false;

        var permission = window.Notification.permission;
        if (permission === "denied") {
            /* The browser will not ask again, and the reader cannot undo
             * it from here. Say so instead of offering a button that
             * cannot work. */
            notifyButton.disabled = true;
            setNotifyLabel("🔕", "Notifications blocked");
            return;
        }
        notifyButton.disabled = false;
        if (permission === "granted" && notifyEnabled()) {
            setNotifyLabel("🔔", "Notifications on");
        } else {
            setNotifyLabel("🔔", "Notify me");
        }
    }

    function showEvent(event) {
        if (!event || !event.key) { return; }
        if (seenKeys().indexOf(event.key) !== -1) {
            /* Already shown. The same rain is not news twice. */
            return;
        }
        rememberKey(event.key);
        try {
            var notification = new window.Notification(event.title, {
                body: event.body,
                tag: event.key
            });
            notification.onclick = function () {
                window.focus();
                notification.close();
            };
        } catch (error) {
            /* The browser refused to show it. Nothing to do about it. */
        }
    }

    function checkForecast() {
        if (typeof window.fetch !== "function") { return; }
        var city = currentCity();
        if (!city) { return; }

        var url = "/api/alert?city=" + encodeURIComponent(city);
        var threshold = savedThreshold();
        if (threshold !== null) {
            url += "&threshold=" + encodeURIComponent(threshold);
        }

        window.fetch(url, {headers: {"Accept": "application/json"}})
            .then(function (response) {
                return response.ok ? response.json() : null;
            })
            .then(function (data) {
                if (!data) { return; }
                if (data.poll_minutes && data.poll_minutes !== pollMinutes) {
                    pollMinutes = data.poll_minutes;
                    startNotifyTimer();
                }
                showEvent(data.event);
            })
            .catch(function () {
                /* The network or the service is down. There is nothing to
                 * say, and nothing to break the page over. */
            });
    }

    function startNotifyTimer() {
        stopNotifyTimer();
        notifyTimer = window.setInterval(
            checkForecast, Math.max(1, pollMinutes) * 60000);
    }

    function stopNotifyTimer() {
        if (notifyTimer !== null) {
            window.clearInterval(notifyTimer);
            notifyTimer = null;
        }
    }

    function onPermissionResult(result) {
        if (result === "granted") {
            setNotifyEnabled(true);
            startNotifyTimer();
            checkForecast();
        }
        updateNotifyButton();
    }

    function onNotifyClick() {
        if (!notificationsSupported()) { return; }
        var permission = window.Notification.permission;
        if (permission === "denied") { return; }

        if (permission === "granted" && notifyEnabled()) {
            /* Switched off again. The browser keeps the permission; the
             * reader only stops being told. */
            setNotifyEnabled(false);
            stopNotifyTimer();
            updateNotifyButton();
            return;
        }

        if (permission === "granted") {
            /* The browser already said yes, and the reader is turning
             * them on now. */
            onPermissionResult("granted");
            return;
        }

        /* The browser only asks for permission from a click, and this is
         * a click. */
        var asked = null;
        try {
            asked = window.Notification.requestPermission();
        } catch (error) {
            asked = null;
        }
        if (asked && typeof asked.then === "function") {
            asked.then(onPermissionResult).catch(function () {
                updateNotifyButton();
            });
        } else {
            try {
                window.Notification.requestPermission(onPermissionResult);
            } catch (error) {
                updateNotifyButton();
            }
        }
    }

    /* --- The service worker --------------------------------------------------
     * The app can be installed on a phone, and it opens without a network.
     * Registering the worker is best-effort: a browser that refuses it, or
     * a page opened over plain HTTP, simply goes on without it. Nothing
     * else in the app depends on it.
     */
    function registerServiceWorker() {
        if (!("serviceWorker" in navigator)) { return; }
        /* A worker only runs in a secure context, which means HTTPS or
         * localhost. */
        if (window.isSecureContext === false) { return; }

        window.addEventListener("load", function () {
            navigator.serviceWorker.register("/service-worker.js")
                .catch(function () {
                    /* The app works without it. Only the offline shell and
                     * the install prompt are lost. */
                });
        });
    }

    /* --- Starting up --------------------------------------------------------- */
    function start() {
        document.documentElement.classList.remove("no-js");
        document.documentElement.classList.add("js");

        registerServiceWorker();

        promotePendingCity();

        var city = savedCity();
        if (rememberBox) {
            rememberBox.checked = city !== "";
        }
        updateRememberLabel(city);

        if (rememberBox) {
            rememberBox.addEventListener("change", onRememberChange);
        }
        if (thresholdInput) {
            thresholdInput.addEventListener("input", onThresholdInput);
            thresholdInput.addEventListener("change", onThresholdChange);
        }
        if (form) {
            form.addEventListener("submit", onSubmit);
        }
        if (notifyButton) {
            notifyButton.addEventListener("click", onNotifyClick);
            updateNotifyButton();
            if (notifyEnabled()
                    && notificationsSupported()
                    && window.Notification.permission === "granted") {
                /* The reader asked for these before and the browser still
                 * says yes. The forecast on the page is fresh, so the
                 * first check waits for the timer. */
                startNotifyTimer();
            }
        }

        refresh();

        /* A start page loads the remembered city by itself, so the reader
         * never has to type it again. Any other page already shows a
         * forecast, and reloading it would throw that away. */
        if (body.getAttribute("data-autoload") === "1" && city) {
            var unit = body.getAttribute("data-unit") || "";
            var url = "?city=" + encodeURIComponent(city);
            if (unit) {
                url += "&unit=" + encodeURIComponent(unit);
            }
            window.location.replace(url);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
