/* ==========================================================================
   CART + SAVED STORAGE — one definition of what CartFlow keeps on the device.

   Why this file exists: the cart used to live entirely inside shop.html, which
   worked while /marketplace was the only page that could add to it. The product
   page at /product/{slug} adds to the same cart, and two pages each writing
   their own idea of the storage shape is how a cart starts losing items — one
   page storing {slug, qty}, the other {slug, quantity}, both blaming the
   browser. The KEYS and the SHAPE are defined here and nowhere else.

   What this file deliberately does NOT do: render. No DOM, no markup, no
   toasts. The Shop draws a full cart sheet with per-business grouping; the
   product page draws a badge and a button. They share the data, not the view —
   a shared renderer would have to know about both, and would grow a flag for
   every difference.

   Every localStorage access is guarded. Storage throws in some private-browsing
   modes, and a blocked cart must degrade to a session-only one rather than take
   the page down with it: reads fall back to empty, writes fail silently, and an
   in-memory copy keeps the page working for as long as the tab is open.

   Doc 13 §3-12 for cart behaviour, doc 12 §19 for Save.
========================================================================== */
(function (window) {
    'use strict';

    var CART_KEY = 'cartflow-cart';
    var SAVED_KEY = 'cartflow-saved';
    var RECENT_KEY = 'cartflow-recent';
    var RECENT_MAX = 8;

    // Used when localStorage is unavailable, so a private window still gets a
    // working cart for the session instead of a button that does nothing.
    var memory = {};

    function readRaw(key) {
        try {
            var stored = window.localStorage.getItem(key);
            if (stored !== null) return JSON.parse(stored);
        } catch (e) { /* fall through to the in-memory copy */ }
        return Object.prototype.hasOwnProperty.call(memory, key) ? memory[key] : null;
    }

    function writeRaw(key, value) {
        memory[key] = value;
        try {
            window.localStorage.setItem(key, JSON.stringify(value));
        } catch (e) { /* session-only from here on */ }
    }

    function toPositiveInt(value, fallback) {
        var n = Math.floor(Number(value));
        return isFinite(n) && n > 0 ? n : fallback;
    }

    /* ---- cart ----
       Lines store ONLY {slug, qty}. Prices, names, images and stock are read
       from the catalogue on every paint, so a cart restored a week later shows
       today's prices — never a stale one the shopper would be charged. */
    function readCart() {
        var raw = readRaw(CART_KEY);
        if (!Array.isArray(raw)) return [];
        var seen = {};
        var lines = [];
        raw.forEach(function (line) {
            if (!line || typeof line.slug !== 'string' || !line.slug) return;
            if (seen[line.slug]) return;          // a duplicated slug is one line
            seen[line.slug] = true;
            lines.push({ slug: line.slug, qty: toPositiveInt(line.qty, 1) });
        });
        return lines;
    }

    function writeCart(lines) {
        writeRaw(CART_KEY, Array.isArray(lines) ? lines : []);
    }

    function unitsIn(lines) {
        return (lines || []).reduce(function (n, line) { return n + toPositiveInt(line.qty, 1); }, 0);
    }

    /* Add `wanted` of `slug`, capped at `stock`.

       Returns {qty, capped} rather than a bare boolean because the caller has to
       tell the truth about what happened: doc 13 §6 says a cart must never
       silently exceed inventory, and "added" and "added as many as exist" are
       different sentences. `capped` is true only when the shopper asked for more
       than the cap allowed. */
    function addToCart(slug, wanted, stock) {
        var lines = readCart();
        var max = Math.max(Math.floor(Number(stock) || 0), 0);
        if (!slug || max === 0) return { qty: 0, capped: false, lines: lines };

        var existing = null;
        for (var i = 0; i < lines.length; i++) {
            if (lines[i].slug === slug) { existing = lines[i]; break; }
        }

        var target = (existing ? existing.qty : 0) + toPositiveInt(wanted, 1);
        var qty = Math.min(target, max);
        if (existing) existing.qty = qty; else lines.push({ slug: slug, qty: qty });

        writeCart(lines);
        return { qty: qty, capped: target > max, lines: lines };
    }

    function qtyOf(slug) {
        var lines = readCart();
        for (var i = 0; i < lines.length; i++) {
            if (lines[i].slug === slug) return lines[i].qty;
        }
        return 0;
    }

    /* ---- saved (doc 12 §19) ----
       Device-local on purpose: there is no `saved_products` table, so a synced
       library would be a promise the account can't keep. The UI says so. */
    function readSaved() {
        var raw = readRaw(SAVED_KEY);
        if (!Array.isArray(raw)) return [];
        return raw.filter(function (slug) { return typeof slug === 'string' && slug; });
    }

    function writeSaved(slugs) {
        writeRaw(SAVED_KEY, Array.isArray(slugs) ? slugs : []);
    }

    function isSaved(slug) {
        return readSaved().indexOf(slug) !== -1;
    }

    /* Returns the NEW state, so the caller can label the button and the toast
       from one call instead of re-reading storage to find out what it just did. */
    function toggleSaved(slug) {
        if (!slug) return false;
        var slugs = readSaved();
        var at = slugs.indexOf(slug);
        if (at === -1) slugs.push(slug); else slugs.splice(at, 1);
        writeSaved(slugs);
        return at === -1;
    }

    /* ---- recently viewed ----
       Written by the product page, read by the Home rail. Slugs only, newest
       first, capped at RECENT_MAX — the rail shows a handful and an unbounded
       list would grow forever in a key nothing prunes.

       Home's rail used to be filled by its own quick-view modal, which meant it
       only ever remembered things you tapped ON Home and forgot them on reload.
       Viewing a product is the thing worth remembering, and that now happens on
       a real page, so the page records it. */
    function readRecent() {
        var raw = readRaw(RECENT_KEY);
        if (!Array.isArray(raw)) return [];
        var seen = {};
        var slugs = [];
        raw.forEach(function (slug) {
            if (typeof slug !== 'string' || !slug || seen[slug]) return;
            seen[slug] = true;
            slugs.push(slug);
        });
        return slugs.slice(0, RECENT_MAX);
    }

    function pushRecent(slug) {
        if (!slug) return readRecent();
        var slugs = readRecent().filter(function (s) { return s !== slug; });
        slugs.unshift(slug);
        slugs = slugs.slice(0, RECENT_MAX);
        writeRaw(RECENT_KEY, slugs);
        return slugs;
    }

    window.CartFlowStore = {
        CART_KEY: CART_KEY,
        SAVED_KEY: SAVED_KEY,
        RECENT_KEY: RECENT_KEY,
        readCart: readCart,
        writeCart: writeCart,
        unitsIn: unitsIn,
        units: function () { return unitsIn(readCart()); },
        addToCart: addToCart,
        qtyOf: qtyOf,
        readSaved: readSaved,
        writeSaved: writeSaved,
        isSaved: isSaved,
        toggleSaved: toggleSaved,
        readRecent: readRecent,
        pushRecent: pushRecent
    };
})(window);
