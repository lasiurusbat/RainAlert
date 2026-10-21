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

    function refresh() {
        var threshold = savedThreshold();
        if (thresholdInput && document.activeElement !== thresholdInput) {
            thresholdInput.value = threshold === null ? "" : String(threshold);
        }
        var counts = applyThreshold(threshold);
        updateStatus(threshold, counts);
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

    /* --- Starting up --------------------------------------------------------- */
    function start() {
        document.documentElement.classList.remove("no-js");
        document.documentElement.classList.add("js");

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
