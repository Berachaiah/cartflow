/* ==========================================================================
   MESSAGES — the whole client (docs/product/10-messaging.md).

   Renders the inbox and the open thread, and keeps both live over the socket at
   /ws/messages. Loaded only by messages.html; the unread badge in the chrome is
   painted by base.html's own script, which this file calls into rather than
   duplicating.

   ONE RENDERER. Every conversation row and every bubble is drawn here and
   nowhere else. Jinja renders the furniture (see partials/thread.html's header
   for why the line is where it is): a bubble has to be drawable from a socket
   frame, so a server-rendered copy would be a second renderer for the same row,
   and the day the two disagree is the day a message reads differently depending
   on whether you scrolled to it or watched it land.

   NOTHING IS FABRICATED. There is no optimistic bubble. A sent message is
   appended from the POST's own response, which carries the real `public_id`,
   the server's `time_label` and the real `expires_at` — a locally-invented
   bubble would have to guess all three, and the disappearing timer makes the
   third one a promise about when the message goes away. The round trip costs a
   few tens of milliseconds; a bubble showing the wrong expiry costs trust. Same
   rule for the badge: a failed refresh leaves the last number rather than
   painting a zero, because "all caught up" is a specific claim.

   THE SOCKET IS AN ACCELERATOR, NOT THE SOURCE. Every frame that changes what
   is on screen also triggers a refetch of the thing it changed. A socket has
   gaps — a sleeping phone, a proxy that dropped an idle connection, the seconds
   between a reconnect and the first frame — and a client that treats push as
   its only source of truth silently diverges across every one of them. So the
   frames make the UI feel instant and the fetches make it correct, and the
   reconnect handler refetches unconditionally.

   NO CSRF HEADER. The app has no CSRF token layer at all; every mutation in it
   relies on the session cookie's SameSite=Lax. Adding a header here would be
   inventing half of a scheme, which reads as protection without being any.

   §22 IN THE COPY. No message in this file ever says "blocked". A block returns
   the same 404 as a handle that never existed, and the whole point of that is
   lost if the client explains the difference. Error wording comes from the
   server (`errorMessage`) precisely so there is one place it is decided.

   Globals it uses: esc, debounce, getJSON, postJSON, patchJSON, delJSON,
   errorMessage, setLoading (cartflow-forms.js); showToast, cfParseEmoji,
   cfPaintMessagesBadge (base.html).
========================================================================== */
(function () {
  "use strict";

  const page = document.querySelector("[data-messages-page]");
  if (!page) return;

  const API = "/api/messages";
  const INBOX_PAGE = 30;
  const PHOTO_MAX_BYTES = 5 * 1024 * 1024; /* app/services/media.py */
  /* The socket drops typing frames that arrive inside 1500ms of the last one
     (ws.py's _TYPING_MIN_INTERVAL), silently. So we stay just outside it rather
     than have our own frames swallowed. */
  const TYPING_EVERY_MS = 1700;
  const TYPING_IDLE_MS = 4000;
  /* The far side clears the indicator on its own after this long without a
     refresh, because a "stop" frame is exactly what the throttle above is most
     likely to eat — it tends to follow a "start" immediately. Without a local
     expiry, one swallowed stop leaves "typing…" on screen for good. */
  const TYPING_EXPIRE_MS = 6500;
  const PING_EVERY_MS = 25000;
  const RECONNECT_MAX_MS = 30000;

  /* ======================================================================
     DOM
     ====================================================================== */
  const $ = (sel, root) => (root || page).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || page).querySelectorAll(sel));

  const el = {
    /* inbox */
    inboxLoading: $("[data-inbox-loading]"),
    inboxRows: $("[data-inbox-rows]"),
    inboxEmpty: $("[data-inbox-empty]"),
    inboxMore: $("[data-inbox-more]"),
    inboxSearch: $("[data-inbox-search]"),
    tabs: $$("[data-filter]"),
    listPane: $(".msg-pane-list"),

    /* thread */
    placeholder: $("[data-thread-placeholder]"),
    thread: $("[data-thread]"),
    back: $("[data-thread-back]"),
    profileLink: $("[data-thread-profile]"),
    avatar: $("[data-thread-avatar]"),
    name: $("[data-thread-name]"),
    sellerMark: $("[data-thread-seller]"),
    presenceDot: $("[data-thread-presence-dot]"),
    presence: $("[data-thread-presence]"),
    timerBtn: $("[data-disappearing-open]"),
    timerLabel: $("[data-disappearing-label]"),

    banner: $("[data-request-banner]"),
    bannerName: $("[data-request-name]"),
    accept: $("[data-request-accept]"),
    decline: $("[data-request-decline]"),

    scroller: $("[data-messages]"),
    loadEarlier: $("[data-load-earlier]"),
    bubbles: $("[data-bubbles]"),
    intro: $("[data-thread-intro]"),
    introBody: $("[data-thread-intro-body]"),

    typing: $("[data-typing]"),
    typingLabel: $("[data-typing-label]"),

    closed: $("[data-composer-closed]"),
    closedReason: $("[data-composer-closed-reason]"),
    composer: $("[data-composer]"),
    body: $("[data-composer-body]"),
    note: $("[data-composer-note]"),
    send: $("[data-composer-send]"),
    photoInput: $("[data-photo-input]"),
    photoOpen: $("[data-photo-open]"),

    /* sheets */
    composeSheet: document.getElementById("composeSheet"),
    composeSearch: $("[data-compose-search]", document),
    composeResults: $("[data-compose-results]", document),
    composeTitle: $("[data-compose-title]", document),
    composeShare: $("[data-compose-share]", document),
    composeShareLabel: $("[data-compose-share-label]", document),
    menuSheet: document.getElementById("threadMenuSheet"),
    menuProfile: $("[data-menu-profile]", document),
    menuDisappearingState: $("[data-menu-disappearing-state]", document),
    menuBlockLabel: $("[data-menu-block-label]", document),
    timerSheet: document.getElementById("disappearingSheet"),
    timerToggle: $("[data-disappearing-toggle]", document),
    reportSheet: document.getElementById("reportSheet"),
    reportForm: $("[data-report-form]", document),
    reportName: $("[data-report-name]", document),
  };

  /* ======================================================================
     STATE

     `open` is the whole open thread: the handle, the conversation's public id
     (null until the first message creates one), the messages oldest-first, and
     the flags that decide what the composer looks like. It is replaced wholesale
     by a thread fetch and never patched from two directions at once.
     ====================================================================== */
  const me = page.dataset.me || "";

  const state = {
    filter: "all",
    query: "",
    rows: [],
    hasMoreRows: false,
    loadingRows: false,
    counts: { unread: 0, requests: 0 },

    open: null,

    /* Handles known to be online. Authoritative only once the socket's `ready`
       frame has landed — before that a row falls back to the `is_active_now`
       the server computed, which is the same answer a moment staler. */
    online: new Set(),
    presenceReady: false,

    socket: null,
    socketTries: 0,
    socketDead: false, /* 4401: the session is gone. Stop trying. */

    /* Set when the page was opened from a Share sheet: {kind, ...} for one
       message the picker is about to send. Cleared as soon as it is sent or the
       sheet is dismissed, so a second visit to the picker is an ordinary one. */
    share: null,
  };

  /* ======================================================================
     SMALL HELPERS
     ====================================================================== */

  /* The same silhouette three other renderers draw — base.html's #cf-avatar
     symbol, cloned rather than copied, so an account with no photo looks
     identical whether Jinja, Discover or this file drew it. */
  function avatarHTML(src, size, radius) {
    const box = `${size} ${radius || "rounded-xl"} shrink-0`;
    if (src) {
      return `<img src="${esc(src)}" alt="" loading="lazy" decoding="async"
                   class="${box} object-cover bg-card" aria-hidden="true">`;
    }
    return `<svg class="${box} overflow-hidden" aria-hidden="true" focusable="false"><use href="#cf-avatar"/></svg>`;
  }

  function nameOf(user) {
    return (user && (user.display_name || user.username)) || "Someone";
  }

  function isOnline(user, fallback) {
    if (!user) return false;
    return state.presenceReady ? state.online.has(user.username) : !!fallback;
  }

  /* A day heading is the one date the server cannot render for us: it is the
     *viewer's* midnight, and the app stores no per-user timezone — which is why
     `absolute_time` labels itself UTC rather than guessing. So this is local, and
     it is the only place a date is formatted client-side. */
  function dayKey(iso) {
    const d = new Date(iso);
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
  }

  function dayLabel(iso) {
    const d = new Date(iso);
    const today = new Date();
    const yesterday = new Date(today.getTime() - 86400000);
    if (dayKey(iso) === dayKey(today.toISOString())) return "Today";
    if (dayKey(iso) === dayKey(yesterday.toISOString())) return "Yesterday";
    const sameYear = d.getFullYear() === today.getFullYear();
    return d.toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: sameYear ? undefined : "numeric",
    });
  }

  /* "43m" for a bubble in its last hour, else "". The last hour only: a "47h"
     that never visibly moves is decoration, and this is the one number worth
     watching change. */
  const COUNTDOWN_FROM_MS = 3600000;
  /* Armed an hour before the countdown is due to appear, because the ticker is
     what makes the number appear at all — a thread left open across the 47-hour
     mark with nothing armed would sit there showing no countdown until something
     else forced a render. */
  const COUNTDOWN_ARM_MS = 2 * COUNTDOWN_FROM_MS;

  function msLeft(expiresAt) {
    return expiresAt ? new Date(expiresAt).getTime() - Date.now() : Infinity;
  }

  function countdown(expiresAt) {
    const left = msLeft(expiresAt);
    if (left <= 0 || left > COUNTDOWN_FROM_MS) return "";
    const mins = Math.floor(left / 60000);
    return mins < 1 ? "<1m" : `${mins}m`;
  }

  function expiresSoon(list) {
    return list.some((m) => msLeft(m.expires_at) <= COUNTDOWN_ARM_MS);
  }

  /* ======================================================================
     SHEETS

     Local, not shared: base.html deliberately namespaces its own create sheet
     as cf* because pages define `openSheet` in their own script blocks. This
     file is one of those, so its handlers stay inside the closure.
     ====================================================================== */
  function openSheet(node) {
    if (!node) return;
    node.classList.add("open");
    document.body.style.overflow = "hidden";
    const focusable = node.querySelector("input, textarea, button");
    if (focusable) setTimeout(() => focusable.focus(), 60);
  }

  function closeSheets() {
    $$(".overlay", document).forEach((o) => o.classList.remove("open"));
    document.body.style.overflow = "";
    /* Dismissing the picker abandons the share. Anything else would leave the
       next person picked receiving something the user had already backed out of. */
    if (state.share) clearShare();
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-close-sheet]")) {
      closeSheets();
      return;
    }
    /* The scrim only — never a click that bubbled out of the panel inside it. */
    if (e.target.classList && e.target.classList.contains("overlay")) closeSheets();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.querySelector(".overlay.open")) closeSheets();
  });

  /* ======================================================================
     INBOX
     ====================================================================== */

  function rowHTML(row) {
    const other = row.other;
    const online = isOnline(other, row.is_active_now);
    const unread = row.unread > 0;

    /* An expired last message leaves the row but not the words: the server
       blanks `preview` and sets `last_message_expired`, and saying "message
       deleted" would be wrong — nothing was deleted, it timed out. */
    let preview;
    if (row.last_message_expired) {
      preview = "Message disappeared";
    } else if (row.preview) {
      preview = (row.preview_is_mine ? "You: " : "") + row.preview;
    } else {
      preview = "No messages yet";
    }

    const badges = [];
    if (row.is_request) badges.push('<span class="text-primary font-semibold">Request</span>');
    if (row.disappearing) {
      badges.push(
        '<span class="material-symbols-outlined text-[13px] align-middle" title="Disappearing messages are on" aria-label="Disappearing messages are on">timer</span>'
      );
    }

    return `
      <button type="button" class="msg-row ${unread ? "is-unread" : ""}"
              data-row="${esc(other.username)}"
              aria-current="${state.open && state.open.handle === other.username}">
        <span class="relative shrink-0">
          ${avatarHTML(other.avatar_url, "w-11 h-11")}
          ${online ? '<span class="msg-dot" title="Active now" aria-label="Active now"></span>' : ""}
        </span>
        <span class="flex-1 min-w-0">
          <span class="flex items-baseline gap-1.5">
            <span class="msg-row-name text-[13.5px] font-semibold text-text truncate">${esc(nameOf(other))}</span>
            ${other.is_seller ? '<span class="material-symbols-outlined text-[14px] text-primary shrink-0" title="Seller" aria-label="Seller">verified</span>' : ""}
            <span class="ml-auto shrink-0 text-[11px] text-muted">${esc(row.time_label)}</span>
          </span>
          <span class="flex items-center gap-1.5 mt-0.5">
            <span class="msg-row-preview flex-1 min-w-0 text-[12.5px] text-muted truncate ${row.last_message_expired ? "italic" : ""}">${esc(preview)}</span>
            ${badges.length ? `<span class="shrink-0 text-[11px] text-muted flex items-center gap-1">${badges.join("")}</span>` : ""}
            ${
              unread
                ? `<span class="shrink-0 min-w-[1.15rem] h-[1.15rem] px-1 rounded-full bg-primary text-background
                                text-[10px] font-bold inline-flex items-center justify-center"
                         aria-label="${row.unread} unread">${row.unread > 99 ? "99+" : row.unread}</span>`
                : ""
            }
          </span>
        </span>
      </button>`;
  }

  function paintTabs() {
    el.tabs.forEach((tab) => {
      tab.setAttribute("aria-selected", String(tab.dataset.filter === state.filter));
    });
    const set = (key, n) => {
      const node = $(`[data-tab-count="${key}"]`);
      if (!node) return;
      node.textContent = n > 99 ? "99+" : String(n);
      node.hidden = n === 0;
    };
    set("unread", state.counts.unread);
    set("requests", state.counts.requests);
  }

  function paintEmpty() {
    const nothing = state.rows.length === 0;
    el.inboxEmpty.hidden = !nothing;
    /* Which nothing it is. A search that found nothing is not an empty inbox,
       and an empty Requests tab is not either — telling someone with forty
       conversations that they have none would be a straightforward lie. */
    const which = state.query ? "search" : state.filter === "all" ? "none" : state.filter;
    $$("[data-empty]", el.inboxEmpty).forEach((node) => {
      node.hidden = node.dataset.empty !== which;
    });
  }

  function paintInbox() {
    el.inboxLoading.hidden = true;
    el.inboxRows.innerHTML = state.rows.map(rowHTML).join("");
    if (window.cfParseEmoji) window.cfParseEmoji(el.inboxRows);
    el.inboxMore.hidden = !state.hasMoreRows;
    paintTabs();
    paintEmpty();
  }

  async function loadInbox() {
    /* Re-read as deep as the user has already scrolled, not just the first page.
       A socket frame arriving while someone is forty rows down must not fold the
       list back up under them. Capped at the endpoint's own ceiling. */
    const depth = Math.min(Math.max(INBOX_PAGE, state.rows.length), 100);
    const params = new URLSearchParams({ filter: state.filter, limit: depth });
    if (state.query) params.set("q", state.query);
    state.loadingRows = true;
    try {
      const data = await getJSON(`${API}?${params}`);
      state.rows = data.items || [];
      state.hasMoreRows = !!data.has_more;
      state.counts = {
        unread: data.unread_conversations || 0,
        requests: data.pending_requests || 0,
      };
      paintInbox();
      /* One number, one owner: the chrome's badge is the same
         `unread_conversations` the tab shows, so they cannot disagree. */
      if (window.cfPaintMessagesBadge) window.cfPaintMessagesBadge(state.counts.unread);
    } catch (err) {
      el.inboxLoading.hidden = true;
      /* Only shout if there is nothing on screen. A refresh that fails while a
         list is already rendered has cost the user nothing they can see. */
      if (!state.rows.length) showToast(errorMessage(err, "Couldn't load your messages."));
    } finally {
      state.loadingRows = false;
    }
  }

  /* The next page, appended. Paged by `offset` off the rows already held, so a
     conversation that jumped to the top between two pages costs a duplicate at
     worst — deduped below rather than pretended away. */
  async function loadMoreRows() {
    if (state.loadingRows || !state.hasMoreRows) return;
    const params = new URLSearchParams({
      filter: state.filter,
      limit: INBOX_PAGE,
      offset: state.rows.length,
    });
    if (state.query) params.set("q", state.query);
    state.loadingRows = true;
    try {
      const data = await getJSON(`${API}?${params}`);
      const seen = new Set(state.rows.map((r) => r.public_id));
      state.rows = state.rows.concat((data.items || []).filter((r) => !seen.has(r.public_id)));
      state.hasMoreRows = !!data.has_more;
      paintInbox();
    } catch (err) {
      /* Silent. The list already on screen is still correct, and a toast for a
         page nobody asked for by name is noise. */
      el.inboxMore.hidden = true;
    } finally {
      state.loadingRows = false;
    }
  }

  if (window.IntersectionObserver) {
    new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) loadMoreRows();
      },
      { rootMargin: "300px" }
    ).observe(el.inboxMore);
  }

  /* Bursts of frames — a reconnect, a fast back-and-forth — should cost one
     request, not one each. */
  const refreshInbox = debounce(loadInbox, 250);

  el.tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      if (state.filter === tab.dataset.filter) return;
      state.filter = tab.dataset.filter;
      /* Dropped, not kept: the depth belongs to the tab you were on, and a new
         tab starts at the top. */
      state.rows = [];
      paintTabs();
      loadInbox();
    });
  });

  el.inboxSearch.addEventListener(
    "input",
    debounce(() => {
      state.query = el.inboxSearch.value.trim();
      state.rows = [];
      loadInbox();
    }, 300)
  );

  el.inboxRows.addEventListener("click", (e) => {
    const row = e.target.closest("[data-row]");
    if (row) navigateTo(row.dataset.row);
  });

  /* ======================================================================
     BUBBLES
     ====================================================================== */

  function shareCardHTML(m) {
    if (m.kind === "shared_profile") {
      if (!m.shared_user) {
        return `<span class="msg-card"><span class="material-symbols-outlined text-[18px] text-muted">person_off</span>
                  <span class="text-[12.5px] text-muted">This account is no longer available</span></span>`;
      }
      const u = m.shared_user;
      return `<a class="msg-card" href="/@${esc(u.username)}">
                ${avatarHTML(u.avatar_url, "w-9 h-9", "rounded-lg")}
                <span class="min-w-0">
                  <span class="block text-[12.5px] font-semibold truncate">${esc(nameOf(u))}</span>
                  <span class="block text-[11px] opacity-70 truncate">@${esc(u.username)}</span>
                </span>
              </a>`;
    }
    /* A shared product travels as its slug and nothing else (see
       Message.shared_product_slug), so the card links out rather than pretending
       to know the title or the price. Fetching them per bubble would be one
       request per card for a line of text. */
    return `<a class="msg-card" href="/product/${esc(m.shared_product_slug)}">
              <span class="w-9 h-9 rounded-lg bg-card border border-border flex items-center justify-center shrink-0">
                <span class="material-symbols-outlined text-[18px] text-muted">sell</span>
              </span>
              <span class="min-w-0">
                <span class="block text-[12.5px] font-semibold">Shared a product</span>
                <span class="block text-[11px] opacity-70 truncate">Open in the shop</span>
              </span>
            </a>`;
  }

  function photoHTML(m) {
    if (!m.image_url) {
      /* The media row was purged but the message was not. The bubble stays as
         the record that something was sent — deleting it would rewrite the
         conversation. */
      return `<span class="msg-card"><span class="material-symbols-outlined text-[18px] text-muted">hide_image</span>
                <span class="text-[12.5px] text-muted">This photo is no longer available</span></span>`;
    }
    return `<a href="${esc(m.image_url)}" target="_blank" rel="noopener">
              <img class="msg-photo" src="${esc(m.image_url)}" alt="Photo" loading="lazy" decoding="async">
            </a>`;
  }

  function tickHTML(m) {
    if (!m.is_mine) return "";
    const seen =
      state.open &&
      state.open.their_last_read_at &&
      new Date(state.open.their_last_read_at) >= new Date(m.sent_at);
    return `<span class="material-symbols-outlined text-[13px]" data-tick
                  title="${seen ? "Seen" : "Sent"}" aria-label="${seen ? "Seen" : "Sent"}"
            >${seen ? "done_all" : "done"}</span>`;
  }

  function bubbleHTML(m) {
    let inner = "";
    if (m.kind === "image") inner += photoHTML(m);
    if (m.kind === "shared_product" || m.kind === "shared_profile") inner += shareCardHTML(m);
    if (m.body) inner += `<span class="block whitespace-pre-wrap">${esc(m.body)}</span>`;

    const left = countdown(m.expires_at);

    return `
      <div class="msg-bubble-row ${m.is_mine ? "is-mine" : ""}"
           data-msg="${esc(m.public_id)}" data-sent-at="${esc(m.sent_at)}"
           ${m.expires_at ? `data-expires-at="${esc(m.expires_at)}"` : ""}>
        <div class="msg-bubble ${m.is_mine ? "is-mine" : "is-theirs"}">
          ${inner}
          <div class="msg-meta">
            <span title="${esc(m.exact_time)}">${esc(m.time_label)}</span>
            ${
              /* Rendered even when it is empty, and hidden instead. The ticker
                 below fills it when the message enters its last hour, and a node
                 that has to be *created* mid-life is a node that never appears
                 on a thread nobody re-rendered. */
              m.expires_at
                ? `<span data-countdown ${left ? "" : "hidden"} class="items-center gap-0.5 inline-flex"
                         title="Disappears from both sides"
                   ><span class="material-symbols-outlined text-[12px]" aria-hidden="true">timer</span><span data-countdown-value>${esc(left)}</span></span>`
                : ""
            }
            ${tickHTML(m)}
          </div>
        </div>
      </div>`;
  }

  function dayHeadingHTML(iso) {
    return `<div class="msg-day"><span>${esc(dayLabel(iso))}</span></div>`;
  }

  function renderBubbles() {
    const list = state.open ? state.open.messages : [];
    let html = "";
    let lastDay = null;
    list.forEach((m) => {
      const key = dayKey(m.sent_at);
      if (key !== lastDay) {
        html += dayHeadingHTML(m.sent_at);
        lastDay = key;
      }
      html += bubbleHTML(m);
    });
    el.bubbles.innerHTML = html;
    if (window.cfParseEmoji) window.cfParseEmoji(el.bubbles);
    armCountdowns();
  }

  /* Appending, rather than re-rendering, for a message that just arrived: a full
     re-render rebuilds every <img> in the thread, and a photo conversation would
     flash top to bottom every time somebody typed "ok". */
  function appendBubble(m) {
    const previous = state.open.messages[state.open.messages.length - 1];
    state.open.messages.push(m);
    let html = "";
    if (!previous || dayKey(previous.sent_at) !== dayKey(m.sent_at)) {
      html += dayHeadingHTML(m.sent_at);
    }
    html += bubbleHTML(m);
    el.bubbles.insertAdjacentHTML("beforeend", html);
    if (window.cfParseEmoji) window.cfParseEmoji(el.bubbles.lastElementChild);
    el.intro.hidden = true;
    armCountdowns();
  }

  function repaintTicks() {
    if (!state.open) return;
    const readAt = state.open.their_last_read_at
      ? new Date(state.open.their_last_read_at)
      : null;
    $$("[data-msg]", el.bubbles).forEach((row) => {
      const tick = row.querySelector("[data-tick]");
      if (!tick) return;
      const seen = readAt && readAt >= new Date(row.dataset.sentAt);
      tick.textContent = seen ? "done_all" : "done";
      tick.title = seen ? "Seen" : "Sent";
      tick.setAttribute("aria-label", tick.title);
    });
  }

  /* ---------------- scroll ---------------- */

  function atBottom() {
    const s = el.scroller;
    return s.scrollHeight - s.scrollTop - s.clientHeight < 80;
  }

  function scrollToBottom() {
    el.scroller.scrollTop = el.scroller.scrollHeight;
  }

  /* ---------------- expiry ---------------- */

  let expiryTimer = null;
  let countdownTimer = null;

  /* One timeout, set to the nearest expiry rather than a poll: a thread open for
     an hour should cost one wake-up, not 120. Rescheduled after every render. */
  function armExpiry() {
    clearTimeout(expiryTimer);
    if (!state.open) return;
    const now = Date.now();
    const next = state.open.messages
      .map((m) => (m.expires_at ? new Date(m.expires_at).getTime() : Infinity))
      .filter((t) => t > now)
      .sort((a, b) => a - b)[0];
    if (!next || next === Infinity) return;
    /* Capped, because setTimeout overflows past ~24.8 days and fires
       immediately — which would drop every bubble in a thread with the timer
       off but a long-dated expiry. */
    const delay = Math.min(next - now + 500, 3600000);
    expiryTimer = setTimeout(sweepExpired, delay);
  }

  function sweepExpired() {
    if (!state.open) return;
    const now = Date.now();
    const before = state.open.messages.length;
    state.open.messages = state.open.messages.filter(
      (m) => !m.expires_at || new Date(m.expires_at).getTime() > now
    );
    if (state.open.messages.length !== before) {
      const wasAtBottom = atBottom();
      renderBubbles();
      el.intro.hidden = state.open.messages.length > 0;
      if (wasAtBottom) scrollToBottom();
      /* The row's preview just went with it. */
      refreshInbox();
    }
    armCountdowns();
  }

  /* The per-bubble countdown only ticks while something is within a couple of
     hours of going, so a thread with the timer off arms no interval at all. */
  function armCountdowns() {
    clearInterval(countdownTimer);
    armExpiry();
    if (!state.open || !expiresSoon(state.open.messages)) return;
    countdownTimer = setInterval(tickCountdowns, 30000);
    tickCountdowns();
  }

  function tickCountdowns() {
    if (!state.open) return clearInterval(countdownTimer);
    state.open.messages.forEach((m) => {
      const row = el.bubbles.querySelector(`[data-msg="${m.public_id}"]`);
      const node = row && row.querySelector("[data-countdown]");
      if (!node) return;
      const left = countdown(m.expires_at);
      node.hidden = !left;
      if (left) node.querySelector("[data-countdown-value]").textContent = left;
    });
  }

  /* ======================================================================
     THREAD
     ====================================================================== */

  function paintPresence() {
    if (!state.open) return;
    const other = state.open.other;
    const online = isOnline(other, state.open.is_active_now);
    el.presenceDot.hidden = !online;
    const label = online ? "Active now" : state.open.last_seen_label || "";
    el.presence.textContent = label;
    /* Repaint the row's dot too — the list is still on screen at lg. */
    const row = el.inboxRows.querySelector(`[data-row="${other.username}"]`);
    if (row) {
      const dot = row.querySelector(".msg-dot");
      if (online && !dot) {
        row
          .querySelector(".relative")
          .insertAdjacentHTML(
            "beforeend",
            '<span class="msg-dot" title="Active now" aria-label="Active now"></span>'
          );
      } else if (!online && dot) {
        dot.remove();
      }
    }
  }

  function paintTimer() {
    const on = !!(state.open && state.open.disappearing);
    const seconds = state.open && state.open.disappear_after_seconds;
    /* The value comes from the server so "48h" is never hardcoded here — the
       timer is one fixed duration today and this label follows it if that
       changes. */
    const label = on ? `${Math.round((seconds || 0) / 3600)}h` : "Off";

    el.timerBtn.hidden = false;
    el.timerBtn.classList.toggle("text-muted", !on);
    el.timerBtn.querySelector(".material-symbols-outlined").textContent = on
      ? "timer"
      : "timer_off";
    el.timerLabel.textContent = label;
    el.timerBtn.setAttribute(
      "aria-label",
      on ? `Disappearing messages on, ${label}` : "Disappearing messages off"
    );
    if (el.timerToggle) el.timerToggle.checked = on;
    if (el.menuDisappearingState) {
      el.menuDisappearingState.textContent = on ? `On · clears after ${label}` : "Off";
    }
  }

  function paintComposer() {
    const t = state.open;
    const handle = "@" + t.other.username;

    el.closed.hidden = t.can_send;
    el.composer.hidden = !t.can_send;
    if (!t.can_send) {
      /* The server's words. It knows which of §6's states this is, and a client
         paraphrase would be a second copy of the state machine's copy. */
      el.closedReason.textContent =
        t.blocked_reason || "You can't send a message in this conversation.";
      return;
    }

    let note = "";
    if (t.is_incoming_request) {
      note = "Replying accepts this request.";
    } else if (!t.conversation) {
      note = `${handle} hasn't messaged you before, so this goes to their requests — one message until they reply.`;
    }
    el.note.textContent = note;
    el.note.hidden = !note;
    el.body.placeholder = t.is_incoming_request ? "Reply to accept" : "Write a message";
  }

  function paintThread(opts) {
    const t = state.open;
    const other = t.other;

    el.placeholder.hidden = true;
    el.thread.hidden = false;

    el.avatar.innerHTML = avatarHTML(other.avatar_url, "w-9 h-9");
    el.name.textContent = nameOf(other);
    el.sellerMark.hidden = !other.is_seller;
    el.profileLink.href = `/@${other.username}`;
    paintPresence();
    paintTimer();

    el.banner.hidden = !t.is_incoming_request;
    if (t.is_incoming_request) el.bannerName.textContent = nameOf(other);

    el.loadEarlier.hidden = !t.has_more;

    renderBubbles();

    el.intro.hidden = t.messages.length > 0;
    if (!t.messages.length) {
      el.introBody.textContent = t.conversation
        ? "Nothing here right now. Messages in this conversation clear on the timer in the header."
        : `This is the start of your conversation with ${nameOf(other)}.`;
    }

    paintComposer();
    hideTyping();

    if (opts && opts.keepScroll) return;
    scrollToBottom();
    el.body.value = "";
    autoGrow();
  }

  async function loadThread(handle, opts) {
    try {
      const data = await getJSON(`${API}/threads/${encodeURIComponent(handle)}`);
      state.open = Object.assign({ handle: handle }, data);
      paintThread(opts);
      markRead();
      /* Repaint the list so the open row is highlighted and its unread pill is
         gone — cheap, and the alternative is the row disagreeing with the pane
         beside it. */
      refreshInbox();
    } catch (err) {
      /* 404 covers an unknown handle, a suspended account and a block, and it
         has to look the same for all three (§22). So: one neutral line, and back
         to the list. */
      closeThread();
      showToast(errorMessage(err, "That conversation isn't available."));
      refreshInbox();
    }
  }

  function closeThread() {
    state.open = null;
    clearTimeout(expiryTimer);
    clearInterval(countdownTimer);
    el.thread.hidden = true;
    el.placeholder.hidden = false;
    document.body.classList.remove("msg-thread-open");
    $$("[data-row]", el.inboxRows).forEach((r) => r.setAttribute("aria-current", "false"));
  }

  /* ---------------- load earlier ---------------- */

  el.loadEarlier.addEventListener("click", async () => {
    if (!state.open || !state.open.messages.length) return;
    const oldest = state.open.messages[0].sent_at;
    setLoading(el.loadEarlier, true);
    try {
      const data = await getJSON(
        `${API}/threads/${encodeURIComponent(state.open.handle)}?before=${encodeURIComponent(oldest)}`
      );
      /* Pin the reading position, not the scroll offset. Prepending grows
         scrollHeight above the viewport, so holding scrollTop would slide the
         thread out from under whoever is reading it — the delta puts the same
         bubble back under the same pixel. */
      const before = el.scroller.scrollHeight;
      const top = el.scroller.scrollTop;
      state.open.messages = (data.messages || []).concat(state.open.messages);
      state.open.has_more = data.has_more;
      el.loadEarlier.hidden = !data.has_more;
      renderBubbles();
      el.scroller.scrollTop = top + (el.scroller.scrollHeight - before);
    } catch (err) {
      showToast(errorMessage(err, "Couldn't load earlier messages."));
    } finally {
      setLoading(el.loadEarlier, false);
    }
  });

  /* ======================================================================
     READ RECEIPTS

     Gated on visibility. A thread open in a background tab must not clear a
     badge — the whole point of the count is that somebody looked.
     ====================================================================== */
  async function markRead() {
    const t = state.open;
    if (!t || !t.conversation || !t.unread) return;
    if (document.visibilityState !== "visible") return;
    const id = t.conversation.public_id;
    t.unread = 0;
    try {
      await postJSON(`${API}/${id}/read`);
      refreshInbox();
    } catch (err) {
      /* Nothing to say. The marker is monotonic server-side, so the next open
         re-sends it and nothing is lost but one round trip. */
    }
  }

  /* ======================================================================
     COMPOSER
     ====================================================================== */

  function autoGrow() {
    el.body.style.height = "auto";
    el.body.style.height = Math.min(el.body.scrollHeight, 128) + "px";
  }

  el.body.addEventListener("input", () => {
    autoGrow();
    pingTyping();
  });

  /* Enter sends, Shift+Enter breaks the line — and neither on a soft keyboard
     mid-composition, where Enter is how you accept a candidate word. */
  el.body.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    e.preventDefault();
    el.composer.requestSubmit();
  });

  el.body.addEventListener("blur", () => stopTyping());

  el.composer.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = el.body.value.trim();
    if (!body || !state.open) return;

    setLoading(el.send, true);
    stopTyping();
    try {
      const res = await postJSON(
        `${API}/threads/${encodeURIComponent(state.open.handle)}`,
        { kind: "text", body: body }
      );
      el.body.value = "";
      autoGrow();
      afterSend(res);
    } catch (err) {
      handleSendError(err);
    } finally {
      setLoading(el.send, false);
    }
  });

  /* One place decides what a send did to the thread, because a photo and a text
     land in exactly the same states. */
  function afterSend(res) {
    if (!state.open) return;
    /* The socket delivers this same message back to my own tabs; `data-msg`
       keyed on public_id is what stops it arriving twice. */
    if (!el.bubbles.querySelector(`[data-msg="${res.message.public_id}"]`)) {
      appendBubble(res.message);
    }
    if (!state.open.conversation) {
      /* The first message created the row. Fetch rather than synthesise it: the
         thread now has a status, a timer and an id, and guessing any of them
         would be inventing state the server just decided. */
      loadThread(state.open.handle, { keepScroll: true });
    } else {
      state.open.conversation.status = res.status;
      if (res.accepted_now) {
        state.open.is_incoming_request = false;
        el.banner.hidden = true;
        paintComposer();
      }
    }
    scrollToBottom();
    refreshInbox();
  }

  /* §6's failures, and what each one means for the words you just typed. The
     message shown is always the server's — only the draft handling is ours. */
  function handleSendError(err) {
    const status = err && err.status;
    showToast(errorMessage(err, "Couldn't send that message."));
    if (status === 409 || status === 429 || status === 422) {
      /* Temporary. Keep the draft — retyping a paragraph because of a rate
         limit is a punishment for the wrong thing. */
      return;
    }
    /* 403 (declined) and 404 (gone, or a block) are both final, and both change
       what the thread looks like. Refetch rather than reason about it here: if
       the thread itself is now unreachable, loadThread's own 404 path closes it. */
    if (state.open) loadThread(state.open.handle, { keepScroll: true });
  }

  /* ---------------- photo ---------------- */

  el.photoOpen.addEventListener("click", () => el.photoInput.click());

  el.photoInput.addEventListener("change", async () => {
    const file = el.photoInput.files && el.photoInput.files[0];
    el.photoInput.value = ""; /* so picking the same file twice still fires */
    if (!file || !state.open) return;

    /* Checked here as well as on the server: a 6MB photo on campus data is a
       long upload to spend on a refusal the client could see coming. */
    if (file.size > PHOTO_MAX_BYTES) {
      showToast("That photo is over 5MB. Try a smaller one.");
      return;
    }

    const form = new FormData();
    form.append("file", file);
    const caption = el.body.value.trim();
    if (caption) form.append("body", caption);

    setLoading(el.photoOpen, true);
    try {
      /* Multipart, so not through sendJSON — the browser has to set its own
         boundary on Content-Type. No CSRF header, same as every other mutation
         in the app. */
      const res = await fetch(
        `${API}/threads/${encodeURIComponent(state.open.handle)}/photo`,
        { method: "POST", body: form, headers: { Accept: "application/json" } }
      );
      const payload = await res.json().catch(() => null);
      if (!res.ok) {
        throw Object.assign(new Error("Upload failed"), { status: res.status, body: payload });
      }
      el.body.value = "";
      autoGrow();
      afterSend(payload);
    } catch (err) {
      handleSendError(err);
    } finally {
      setLoading(el.photoOpen, false);
    }
  });

  /* ======================================================================
     TYPING (§18)
     ====================================================================== */
  let lastTypingSent = 0;
  let typingIdle = null;
  let typingClear = null;

  function sendTyping(stateName) {
    if (!state.open || !state.open.conversation) return;
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return;
    state.socket.send(
      JSON.stringify({
        type: "typing",
        conversation: state.open.conversation.public_id,
        state: stateName,
      })
    );
  }

  function pingTyping() {
    const now = Date.now();
    if (now - lastTypingSent > TYPING_EVERY_MS) {
      lastTypingSent = now;
      sendTyping("start");
    }
    clearTimeout(typingIdle);
    typingIdle = setTimeout(stopTyping, TYPING_IDLE_MS);
  }

  function stopTyping() {
    clearTimeout(typingIdle);
    if (!lastTypingSent) return;
    lastTypingSent = 0;
    sendTyping("stop");
  }

  function showTyping(name) {
    el.typingLabel.textContent = `${name} is typing`;
    /* Measured before the row appears, because appearing shrinks the scroller
       and clamps scrollTop — asking afterwards always answers "yes". */
    const stick = atBottom();
    el.typing.hidden = false;
    if (stick) scrollToBottom();
    clearTimeout(typingClear);
    typingClear = setTimeout(hideTyping, TYPING_EXPIRE_MS);
  }

  function hideTyping() {
    clearTimeout(typingClear);
    el.typing.hidden = true;
  }

  /* ======================================================================
     ACTIONS
     ====================================================================== */

  function conversationId() {
    return state.open && state.open.conversation && state.open.conversation.public_id;
  }

  el.accept.addEventListener("click", async () => {
    const id = conversationId();
    if (!id) return;
    setLoading(el.accept, true);
    try {
      await postJSON(`${API}/${id}/accept`);
      await loadThread(state.open.handle, { keepScroll: true });
    } catch (err) {
      showToast(errorMessage(err, "Couldn't accept that request."));
    } finally {
      setLoading(el.accept, false);
    }
  });

  el.decline.addEventListener("click", async () => {
    const id = conversationId();
    if (!id) return;
    /* Confirmed, because it cannot be undone from this side and the wording in
       the banner is "Delete". */
    if (!window.confirm("Delete this request? They won't be told, and they can't write again.")) {
      return;
    }
    setLoading(el.decline, true);
    try {
      await postJSON(`${API}/${id}/decline`);
      closeThread();
      pushUrl("/messages");
      showToast("Request deleted.");
      loadInbox();
    } catch (err) {
      showToast(errorMessage(err, "Couldn't delete that request."));
    } finally {
      setLoading(el.decline, false);
    }
  });

  document.addEventListener("click", async (e) => {
    /* ---- open the sheets ---- */
    if (e.target.closest("[data-compose-open]")) {
      if (state.share) openShareCompose();
      else {
        openSheet(el.composeSheet);
        loadCandidates("");
      }
      return;
    }
    if (e.target.closest("[data-thread-menu-open]")) {
      if (!state.open) return;
      el.menuProfile.href = `/@${state.open.other.username}`;
      el.menuBlockLabel.textContent = `Block ${nameOf(state.open.other)}`;
      openSheet(el.menuSheet);
      return;
    }
    if (e.target.closest("[data-disappearing-open]") || e.target.closest("[data-menu-disappearing]")) {
      if (!conversationId()) {
        showToast("Send a message first — there's no conversation to set a timer on yet.");
        return;
      }
      paintTimer();
      closeSheets();
      openSheet(el.timerSheet);
      return;
    }
    if (e.target.closest("[data-menu-report]")) {
      if (!state.open) return;
      el.reportName.textContent = nameOf(state.open.other);
      closeSheets();
      openSheet(el.reportSheet);
      return;
    }

    /* ---- archive ---- */
    if (e.target.closest("[data-menu-archive]")) {
      const id = conversationId();
      if (!id) return closeSheets();
      try {
        await postJSON(`${API}/${id}/archive`);
        closeSheets();
        closeThread();
        pushUrl("/messages");
        showToast("Conversation archived. It'll come back if they write again.");
        loadInbox();
      } catch (err) {
        showToast(errorMessage(err, "Couldn't archive that."));
      }
      return;
    }

    /* ---- block ---- */
    if (e.target.closest("[data-menu-block]")) {
      if (!state.open) return closeSheets();
      const handle = state.open.other.username;
      if (
        !window.confirm(
          `Block ${nameOf(state.open.other)}? They won't be able to message you or find your profile, and this conversation disappears from both inboxes.`
        )
      ) {
        return;
      }
      try {
        await postJSON(`${API}/blocks/${encodeURIComponent(handle)}`);
        closeSheets();
        closeThread();
        pushUrl("/messages");
        showToast("Blocked. You can undo this from their profile.");
        loadInbox();
      } catch (err) {
        showToast(errorMessage(err, "Couldn't block that account."));
      }
      return;
    }
  });

  /* ---- disappearing ---- */
  if (el.timerToggle) {
    el.timerToggle.addEventListener("change", async () => {
      const id = conversationId();
      const wanted = el.timerToggle.checked;
      if (!id) {
        el.timerToggle.checked = !wanted;
        return;
      }
      try {
        const res = await patchJSON(`${API}/${id}/disappearing`, { enabled: wanted });
        state.open.disappearing = res.disappearing;
        state.open.disappear_after_seconds = res.disappear_after_seconds;
        paintTimer();
        showToast(
          res.disappearing
            ? "Disappearing messages on for new messages."
            : "Disappearing messages off for new messages."
        );
        refreshInbox();
      } catch (err) {
        /* Put the checkbox back where the server left it, or the control is
           lying about the state of the thread. */
        el.timerToggle.checked = !wanted;
        showToast(errorMessage(err, "Couldn't change that setting."));
      }
    });
  }

  /* ---- report ---- */
  if (el.reportForm) {
    el.reportForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!state.open) return;
      const data = new FormData(el.reportForm);
      const button = el.reportForm.querySelector('button[type="submit"]');
      setLoading(button, true);
      try {
        await postJSON(`${API}/reports/${encodeURIComponent(state.open.other.username)}`, {
          reason: data.get("reason"),
          note: data.get("note") || null,
          conversation_public_id: conversationId() || null,
        });
        closeSheets();
        el.reportForm.reset();
        showToast("Report sent. CartFlow admins will look at it.");
      } catch (err) {
        showToast(errorMessage(err, "Couldn't send that report."));
      } finally {
        setLoading(button, false);
      }
    });
  }

  /* ======================================================================
     COMPOSE PICKER
     ====================================================================== */
  async function loadCandidates(query) {
    el.composeResults.innerHTML =
      '<p class="py-6 text-center caption-text text-[12.5px]">Loading…</p>';
    try {
      const params = new URLSearchParams();
      if (query) params.set("q", query);
      const data = await getJSON(`${API}/candidates?${params}`);
      const items = data.items || [];
      if (!items.length) {
        el.composeResults.innerHTML = `<p class="py-6 text-center caption-text text-[12.5px]">${
          query ? "Nobody matching that." : "Follow someone first, or start from their profile."
        }</p>`;
        return;
      }
      el.composeResults.innerHTML = items
        .map(
          (u) => `
          <button type="button" data-pick="${esc(u.username)}"
                  class="w-full flex items-center gap-3 py-2.5 text-left hover:bg-glass rounded-xl px-2">
            ${avatarHTML(u.avatar_url, "w-10 h-10")}
            <span class="min-w-0 flex-1">
              <span class="flex items-center gap-1">
                <span class="block text-[13.5px] font-semibold truncate">${esc(nameOf(u))}</span>
                ${u.is_seller ? '<span class="material-symbols-outlined text-[14px] text-primary shrink-0" title="Seller">verified</span>' : ""}
              </span>
              <span class="block text-[11.5px] text-muted truncate">@${esc(u.username)}${
                u.organization_name ? " · " + esc(u.organization_name) : ""
              }</span>
            </span>
          </button>`
        )
        .join("");
      if (window.cfParseEmoji) window.cfParseEmoji(el.composeResults);
    } catch (err) {
      el.composeResults.innerHTML =
        '<p class="py-6 text-center caption-text text-[12.5px]">Couldn\'t load that list.</p>';
    }
  }

  if (el.composeSearch) {
    el.composeSearch.addEventListener(
      "input",
      debounce(() => loadCandidates(el.composeSearch.value.trim()), 300)
    );
  }

  if (el.composeResults) {
    el.composeResults.addEventListener("click", (e) => {
      const pick = e.target.closest("[data-pick]");
      if (!pick) return;
      if (state.share) sendShareTo(pick);
      else {
        closeSheets();
        navigateTo(pick.dataset.pick);
      }
    });
  }

  /* ---------------- share mode ----------------

     Arriving from a Share sheet elsewhere: pick a person and the share is sent,
     rather than dropped into a composer for them to press send on. That is the
     behaviour every share sheet in every app has trained, and a draft the user
     then has to confirm turns one tap into three.

     Sent from here rather than from the route that carried the slug, because a
     GET that sends a message sends it again on every refresh. */
  function shareLabel(share) {
    return share.kind === "shared_profile"
      ? `Sending @${share.shared_username}'s profile.`
      : "Sending this product.";
  }

  function openShareCompose() {
    el.composeTitle.textContent = "Send to";
    el.composeShareLabel.textContent = shareLabel(state.share);
    el.composeShare.hidden = false;
    openSheet(el.composeSheet);
    loadCandidates("");
  }

  function clearShare() {
    state.share = null;
    el.composeTitle.textContent = "New message";
    el.composeShare.hidden = true;
    /* The query string goes too. Leaving ?share= on the URL means a refresh
       re-opens a picker for something the user already sent or dismissed. */
    if (location.search) history.replaceState({}, "", location.pathname);
  }

  async function sendShareTo(pick) {
    const handle = pick.dataset.pick;
    const payload = Object.assign({}, state.share);
    setLoading(pick, true);
    try {
      await postJSON(`${API}/threads/${encodeURIComponent(handle)}`, payload);
      clearShare();
      closeSheets();
      showToast("Sent.");
      navigateTo(handle);
    } catch (err) {
      /* Left open on failure, with the share still pending: the picker is where
         the retry happens, and closing it would lose what they were sending. */
      showToast(errorMessage(err, "Couldn't send that."));
    } finally {
      setLoading(pick, false);
    }
  }

  /* ======================================================================
     ROUTING

     The thread is a URL, so the phone's back gesture works, a conversation can
     be linked to from a profile, and a refresh keeps you where you were.
     `pushState` rather than navigation: the shell is already loaded, and at lg
     the list must not blink away just because you opened a thread.
     ====================================================================== */
  function pushUrl(path) {
    if (location.pathname !== path) history.pushState({}, "", path);
  }

  function navigateTo(handle) {
    pushUrl(`/messages/@${handle}`);
    openThread(handle);
  }

  function openThread(handle) {
    document.body.classList.add("msg-thread-open");
    /* Placeholder off, thread on, before the fetch: at lg the pane is already
       visible, and leaving "Your messages" up while a thread loads reads as the
       click having missed. */
    el.placeholder.hidden = true;
    loadThread(handle);
  }

  el.back.addEventListener("click", () => {
    /* Back through history, not a direct close, so the URL and the pane cannot
       disagree — and so a second back press leaves /messages rather than
       walking back through every thread you opened. */
    history.back();
  });

  window.addEventListener("popstate", () => {
    const match = location.pathname.match(/^\/messages\/@(.+)$/);
    if (match) openThread(decodeURIComponent(match[1]));
    else closeThread();
  });

  /* ======================================================================
     SOCKET
     ====================================================================== */
  function socketURL() {
    const scheme = location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${location.host}/ws/messages`;
  }

  let pingTimer = null;

  function connect() {
    if (state.socketDead) return;
    let socket;
    try {
      socket = new WebSocket(socketURL());
    } catch (err) {
      scheduleReconnect();
      return;
    }
    state.socket = socket;

    socket.addEventListener("open", () => {
      state.socketTries = 0;
      /* Close the gap. Whatever happened while the socket was down did not
         arrive as a frame, so the only correct move on connect is to re-read
         both views — this is what makes push an accelerator rather than the
         source of truth. */
      loadInbox();
      if (state.open) loadThread(state.open.handle, { keepScroll: true });
      clearInterval(pingTimer);
      pingTimer = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "ping" }));
        }
      }, PING_EVERY_MS);
    });

    socket.addEventListener("message", (event) => {
      let frame;
      try {
        frame = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      handleFrame(frame);
    });

    socket.addEventListener("close", (event) => {
      clearInterval(pingTimer);
      state.socket = null;
      if (event.code === 4401) {
        /* The session is gone. Reconnecting would just be refused in a loop,
           and every fetch on this page is about to 401 too, so say so once and
           stop. */
        state.socketDead = true;
        showToast("You've been signed out. Reload to sign back in.");
        return;
      }
      scheduleReconnect();
    });
  }

  function scheduleReconnect() {
    if (state.socketDead) return;
    /* Exponential with jitter: without it, every client that dropped when a
       server restarted comes back in the same millisecond. */
    const base = Math.min(1000 * Math.pow(2, state.socketTries), RECONNECT_MAX_MS);
    const wait = base / 2 + Math.random() * (base / 2);
    state.socketTries += 1;
    setTimeout(connect, wait);
  }

  function handleFrame(frame) {
    switch (frame.type) {
      case "ready":
        state.online = new Set(frame.online || []);
        state.presenceReady = true;
        paintInbox();
        if (state.open) paintPresence();
        break;

      case "presence":
        if (frame.online) state.online.add(frame.username);
        else state.online.delete(frame.username);
        if (state.open && state.open.other.username === frame.username) paintPresence();
        else refreshInbox();
        break;

      case "message": {
        /* Matched on `other` first, not the conversation id. The id is null on a
           thread you have opened but never sent in — and their first message is
           exactly what creates it, so an id match would miss the one frame that
           matters most. `other` is already the counterpart from this viewer's
           side, which is why the server sends it per recipient. */
        const here =
          state.open &&
          (frame.other === state.open.handle || frame.conversation === conversationId());
        if (here) {
          hideTyping();
          if (!state.open.conversation) {
            /* The conversation exists now and this client has never seen its
               status, timer or id. Read it rather than assemble it. */
            loadThread(state.open.handle, { keepScroll: true });
          } else if (!el.bubbles.querySelector(`[data-msg="${frame.message.public_id}"]`)) {
            const stick = atBottom() || frame.message.is_mine;
            appendBubble(frame.message);
            if (stick) scrollToBottom();
          }
          if (frame.accepted_now) {
            state.open.is_incoming_request = false;
            el.banner.hidden = true;
          }
          if (state.open.conversation) state.open.conversation.status = frame.status;
          if (!frame.message.is_mine && state.open.conversation) {
            state.open.unread = (state.open.unread || 0) + 1;
            markRead();
            /* An incoming message can unlock a composer §6 had closed — they
               replied, so the one-message hold is over. */
            if (!state.open.can_send) loadThread(state.open.handle, { keepScroll: true });
          }
        }
        refreshInbox();
        break;
      }

      case "read":
        if (state.open && frame.conversation === conversationId()) {
          state.open.their_last_read_at = frame.at;
          repaintTicks();
        }
        break;

      case "typing":
        if (!state.open || frame.conversation !== conversationId()) return;
        if (frame.state === "stop") hideTyping();
        else showTyping(nameOf(state.open.other));
        break;

      case "conversation_state":
        if (state.open && frame.conversation === conversationId()) {
          if (frame.archived) {
            closeThread();
            pushUrl("/messages");
          } else {
            loadThread(state.open.handle, { keepScroll: true });
          }
        }
        refreshInbox();
        break;

      case "conversation_settings":
        if (state.open && frame.conversation === conversationId()) {
          state.open.disappearing = frame.disappearing;
          state.open.disappear_after_seconds = frame.disappear_after_seconds;
          paintTimer();
          /* Both sides are told, including the one who did it — that tab's own
             toast already fired, so only announce somebody else's change. */
          if (frame.username !== me) {
            showToast(
              frame.disappearing
                ? `${nameOf(state.open.other)} turned on disappearing messages.`
                : `${nameOf(state.open.other)} turned off disappearing messages.`
            );
          }
        }
        refreshInbox();
        break;

      default:
        /* `pong`, and anything a newer server sends. Ignored rather than
           logged: an unknown frame is a server ahead of this file, not a bug. */
        break;
    }
  }

  /* ======================================================================
     BOOT
     ====================================================================== */

  /* Coming back to the tab: re-read, and clear the badge for the thread that is
     already on screen — which could not be marked read while the tab was hidden. */
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    loadInbox();
    if (state.open) {
      loadThread(state.open.handle, { keepScroll: true });
    }
  });

  loadInbox();

  const initialHandle = page.dataset.openHandle;
  if (initialHandle) openThread(initialHandle);

  /* A Share sheet somewhere else handed us something to send. The picker opens
     straight away rather than waiting for a tap — the user already chose "send in
     a message", and an inbox that just sat there would look like the share had
     been swallowed. */
  const shareSlug = page.dataset.shareSlug;
  const shareUser = page.dataset.shareUser;
  if (shareSlug) {
    state.share = { kind: "shared_product", shared_product_slug: shareSlug };
  } else if (shareUser) {
    state.share = { kind: "shared_profile", shared_username: shareUser };
  }
  if (state.share) openShareCompose();

  connect();
})();
