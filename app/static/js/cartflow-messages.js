(() => {
  'use strict';
  const root = document.getElementById('cm'); if (!root) return;
  const $ = id => document.getElementById(id), D = root.dataset;
  const shell = $('cm-shell'), rowsEl = $('cm-rows'), msgsEl = $('cm-msgs'), wrapEl = msgsEl.parentElement, input = $('cm-input'), note = $('cm-note'), layer = $('cm-layer'), info = $('cm-info');
  const reasons = (() => { try { return JSON.parse($('cm-reasons').textContent) || []; } catch { return []; } })();
  const WPS = [['default','Default'],['dots','Dots'],['grid','Grid'],['lines','Lines'],['sky','Sky'],['mint','Mint'],['peach','Peach'],['lilac','Lilac']];
  const RATIOS = [['9:16', 9 / 16, 'Phone 9:16'], ['3:4', 3 / 4, 'Tall 3:4'], ['1:1', 1, 'Square 1:1'], ['16:9', 16 / 9, 'Wide 16:9']];
  const EMOJI = '😀 😂 😊 😍 🥰 😘 😎 🤩 🥳 😅 🤣 🙂 😉 😇 🤔 😮 😢 😭 😡 😴 🙏 👍 👎 👏 🙌 💪 🤝 👋 ❤️ 🔥 ✨ 🎉 💯 ✅ ❌ 👀 🎁 🛍️ 📦 💸 🏠 🎓 📚 ☕ 🍕 🚗 📍'.split(' ');
  let inbox = {items: [], unread_conversations: 0, pending_requests: 0}, tab = 'all', q = '', active = null, thread = null;
  let online = new Set(), typingUntil = 0, lastTyping = 0, ws = null, pending = null, infoOpen = false, infoTab = 'media';
  let pins = {list: [], ids: new Set(), max: 5};
  let deal = {product: null};
  let wp = {kind: 'preset', preset: 'default', image_url: null, focus_x: .5, focus_y: .5, dim: 0, scope: 'none'};
  let search = {on: false, q: '', hits: 0, i: 0};
  // The message this draft is quoting, or null. Held here rather than in the DOM
  // so a re-render of the thread cannot lose it.
  let replyTo = null;
  const REACTION_EMOJI = ['❤️', '😂', '😮', '😢', '👍', '🔥'];

  /* ---------- helpers ---------- */
  const h = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
  const ico = (n, c = '') => { const s = h('span', 'material-symbols-outlined ' + c, n); s.setAttribute('aria-hidden', 'true'); return s; };
  const btn = (c, label) => { const b = h('button', c); b.type = 'button'; if (label) b.setAttribute('aria-label', label); return b; };
  const enc = encodeURIComponent;
  const nameOf = u => u.display_name || u.name || u.full_name || u.username || '';
  const picOf = u => u.avatar_url || u.profile_image_url || u.avatar || u.image_url || null;
  const photoOf = m => m.image_url || m.photo_url || m.media_url || null;
  const tfmt = d => d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'}).toLowerCase();
  const dayLabel = d => { const t = new Date(), y = new Date(Date.now() - 864e5); if (d.toDateString() === t.toDateString()) return 'Today'; if (d.toDateString() === y.toDateString()) return 'Yesterday'; return d.toLocaleDateString(undefined, {weekday: 'short', day: 'numeric', month: 'short', year: d.getFullYear() === t.getFullYear() ? undefined : 'numeric'}); };
  const errText = (d, t) => { if (!d) return (t || '').slice(0, 200); const x = d.detail ?? d.message ?? d.error; if (typeof x === 'string') return x; if (Array.isArray(x)) return x.map(i => i.msg || JSON.stringify(i)).join('; '); if (x && x.message) return x.message; return JSON.stringify(d).slice(0, 200); };
  async function api(path, method = 'GET', body) {
    const fd = body instanceof FormData;
    const r = await fetch(path, {method, credentials: 'same-origin', headers: body && !fd ? {'Content-Type': 'application/json'} : {}, body: body ? (fd ? body : JSON.stringify(body)) : undefined});
    const t = await r.text(); let d = null; try { d = JSON.parse(t); } catch {}
    if (!r.ok) { const e = new Error(errText(d, t)); e.status = r.status; throw e; }
    return d;
  }
  let toastT; function toast(msg) { document.querySelectorAll('.cm-toast').forEach(e => e.remove()); const t = h('div', 'cm-toast', msg); document.body.append(t); clearTimeout(toastT); toastT = setTimeout(() => t.remove(), 2800); }
  function avatar(u, size) {
    const a = h('div', 'cm-av'); a.style.cssText = `width:${size}px;height:${size}px;font-size:${Math.round(size * .36)}px`;
    const p = picOf(u); if (p) { const i = h('img'); i.src = p; i.alt = ''; a.append(i); } else a.append((nameOf(u)[0] || '?').toUpperCase());
    if (online.has(u.username)) a.append(h('i')); return a;
  }
  function lightbox(src) { const l = h('div', 'cm-lb'); const i = h('img'); i.src = src; i.alt = 'Photo'; l.append(i); l.onclick = () => l.remove(); document.body.append(l); }
  function sheet(title, build) {
    const o = h('div', 'cm-over'), s = h('div', 'cm-sheet'), hd = h('h3', '', title), x = btn('cm-ib sm', 'Close'); x.append(ico('close'));
    const close = () => o.remove(); x.onclick = close; hd.append(x); s.append(hd); build(s, close); o.append(s); o.onclick = e => { if (e.target === o) close(); }; layer.append(o); return close;
  }

  /* ---------- fit to the screen ---------- */
  function fit() {
    const lg = matchMedia('(min-width:1024px)').matches, inset = lg ? 12 : 0, main = root.closest('main');
    let t = 0, r = 0, bt = 0, l = 0;
    for (let el = root.parentElement; el; el = el.parentElement) {
      const cs = getComputedStyle(el);
      t += parseFloat(cs.paddingTop) || 0; r += parseFloat(cs.paddingRight) || 0;
      bt += parseFloat(cs.paddingBottom) || 0; l += parseFloat(cs.paddingLeft) || 0;
      if (el === main) break;
    }
    root.style.margin = `${inset - t}px ${inset - r}px ${inset - bt}px ${inset - l}px`;
    const top = root.getBoundingClientRect().top; let bottom = 0;
    if (!lg) for (const n of document.querySelectorAll('nav,footer')) { const q = n.getBoundingClientRect(); if (getComputedStyle(n).position === 'fixed' && q.top > innerHeight / 2 && q.height > 0) bottom = Math.max(bottom, innerHeight - q.top); }
    shell.style.height = Math.max(320, innerHeight - top - bottom - inset) + 'px';
  }
  addEventListener('resize', fit);

  /* ---------- wallpaper (server-side) ---------- */
  function paintWp(el, w) {
    el.style.backgroundImage = el.style.backgroundSize = el.style.backgroundPosition = '';
    [...el.classList].filter(c => c.startsWith('wp-')).forEach(c => el.classList.remove(c));
    if (w.kind === 'photo' && w.image_url) { const d = (w.dim || 0) / 100; el.style.backgroundImage = `linear-gradient(rgba(20,33,61,${d}),rgba(20,33,61,${d})),url("${w.image_url}")`; el.style.backgroundSize = 'cover'; el.style.backgroundPosition = `${(w.focus_x ?? .5) * 100}% ${(w.focus_y ?? .5) * 100}%`; }
    else el.classList.add('wp-' + (w.preset || 'default'));
  }
  const applyWp = () => paintWp(wrapEl, wp);
  async function loadWallpaper() { const c = thread && thread.conversation; try { wp = await api('/api/messages/wallpaper' + (c ? '?conversation=' + c.public_id : '')); } catch {} applyWp(); if (infoOpen) renderInfo(); }

  /* ---------- pins ---------- */
  function setPins(r) { pins = {list: r.pins || [], ids: new Set((r.pins || []).map(p => p.message.public_id)), max: r.max || 5}; if (thread) renderThread(false); if (infoOpen) renderInfo(); }
  async function loadPins() { const c = thread && thread.conversation; if (!c) { pins = {list: [], ids: new Set(), max: 5}; return; } try { setPins(await api(`/api/messages/${c.public_id}/pins`)); } catch {} }
  async function togglePin(m) { const c = thread.conversation, was = pins.ids.has(m.public_id); try { setPins(await api(`/api/messages/${c.public_id}/pins/${m.public_id}`, was ? 'DELETE' : 'POST')); toast(was ? 'Unpinned' : `Pinned · ${pins.list.length} of ${pins.max}`); } catch (e) { toast(e.message); } }
  function closeMenu() { const m = $('cm-menu'); if (m) m.remove(); }
  function msgMenu(m, el) {
    closeMenu(); if (!thread || !thread.conversation) return;
    const box = h('div', 'cm-menu'); box.id = 'cm-menu', was = pins.ids.has(m.public_id);
    const item = (i, label, fn) => { const b = btn('cm-mi'); b.append(ico(i), h('span', '', label)); b.onclick = e => { e.stopPropagation(); closeMenu(); fn(); }; box.append(b); };
    // Reaction picker first: it is the most-used action on a long-press menu and
    // putting it above the list means a thumb does not have to travel.
    const rxp = h('div', 'cm-rxp');
    REACTION_EMOJI.forEach(e => { const b = btn('', 'React ' + e); b.textContent = e; b.onclick = ev => { ev.stopPropagation(); closeMenu(); reactTo(m, e); }; rxp.append(b); });
    box.append(rxp);
    item('reply', 'Reply', () => setReply(m));
    item('push_pin', was ? 'Unpin message' : `Pin message · ${pins.list.length} of ${pins.max}`, () => togglePin(m));
    if (m.is_mine) item('delete', 'Delete for everyone', () => deleteMsg(m));
    if (m.body) item('content_copy', 'Copy text', () => { (navigator.clipboard ? navigator.clipboard.writeText(m.body) : Promise.reject()).then(() => toast('Copied'), () => toast("Couldn't copy")); });
    document.body.append(box);
    const r = el.getBoundingClientRect(), bw = box.offsetWidth, bh = box.offsetHeight;
    let left = m.is_mine ? r.right - bw : r.left; left = Math.max(8, Math.min(left, innerWidth - bw - 8));
    let top = r.bottom + 6; if (top + bh > innerHeight - 8) top = Math.max(8, r.top - bh - 6);
    box.style.left = left + 'px'; box.style.top = top + 'px';
  }
  /* ---------- reply, react, delete ---------- */
  function quoteEl(m) {
    const q = h('div', 'cm-quote' + (m.reply_deleted ? ' gone' : '')), t = h('div', 'qt');
    q.append(h('span', 'qb'));
    t.append(h('span', 'qn', m.reply_is_mine ? 'You' : nameOf(thread.other)));
    t.append(h('span', 'qs', m.reply_deleted ? 'This message was deleted' : (m.reply_body || 'Message')));
    q.append(t);
    // A quote is a doorway, not decoration: tapping it jumps to the original.
    q.onclick = e => { e.stopPropagation(); if (m.reply_public_id) jumpTo(m.reply_public_id); };
    return q;
  }
  function setReply(m) {
    replyTo = m || null;
    const bar = $('cm-reply'); if (!bar) return;
    bar.hidden = !replyTo;
    if (replyTo) {
      $('cm-reply-who').textContent = replyTo.is_mine ? 'You' : nameOf(thread.other);
      $('cm-reply-snip').textContent = replyTo.body || 'Photo';
      input.focus();
    }
  }
  async function reactTo(m, emoji) {
    const c = thread && thread.conversation; if (!c) return;
    try {
      await api(`/api/messages/${c.public_id}/messages/${m.public_id}/reactions`, 'POST', {emoji});
      await loadThread(active, false);
    } catch (e) { toast(e.message); }
  }
  async function deleteMsg(m) {
    const c = thread && thread.conversation; if (!c) return;
    if (!confirm('Delete this message for everyone?')) return;
    try {
      await api(`/api/messages/${c.public_id}/messages/${m.public_id}`, 'DELETE');
      await loadThread(active, false); loadInbox();
    } catch (e) { toast(e.message); }
  }
  /* ---------- per-row menu (archive / block / delete) ---------- */
  async function rowAction(fn) {
    try { await fn(); } catch (e) { toast(e.message); }
  }
  function rowMenu(c, anchor) {
    closeMenu();
    const box = h('div', 'cm-row-menu');
    const item = (icon, label, cls, fn) => {
      const b = btn('cm-mi' + (cls ? ' ' + cls : ''));
      b.append(ico(icon), h('span', '', label));
      b.onclick = e => { e.stopPropagation(); closeMenu(); fn(); };
      box.append(b);
      return b;
    };
    // Order is least-destructive first, so a thumb aiming at "Archive" cannot
    // land on "Delete" because the list moved.
    item('archive', 'Archive chat', '', () => rowAction(async () => {
      await api(`/api/messages/${c.public_id}/archive`, 'POST');
      if (active === c.other.username) closeThread();
      loadInbox(); toast('Archived — it comes back if they write');
    }));
    item('block', `Block @${c.other.username}`, 'red', () => rowAction(async () => {
      if (!confirm(`Block @${c.other.username}? You won't see each other's messages.`)) return;
      await api('/api/messages/blocks/' + enc(c.other.username), 'POST');
      if (active === c.other.username) closeThread();
      loadInbox(); toast('Blocked');
    }));
    item('delete', 'Delete chat', 'red', () => rowAction(async () => {
      if (!confirm('Delete this chat from your inbox? The other person keeps their copy.')) return;
      await api(`/api/messages/${c.public_id}/delete`, 'POST');
      if (active === c.other.username) closeThread();
      loadInbox(); toast('Chat deleted');
    }));

    document.body.append(box);
    const r = anchor.getBoundingClientRect(), bw = box.offsetWidth, bh = box.offsetHeight;
    let left = r.right - bw; left = Math.max(8, Math.min(left, innerWidth - bw - 8));
    let top = r.bottom + 6; if (top + bh > innerHeight - 8) top = Math.max(8, r.top - bh - 6);
    box.style.left = left + 'px'; box.style.top = top + 'px';
  }
  function jumpTo(id) {
    const el = msgsEl.querySelector(`[data-id="${id}"]`); if (!el) { toast('That message is further back in the chat'); return; }
    if (matchMedia('(max-width:1023px)').matches) { infoOpen = false; info.hidden = true; }
    el.scrollIntoView({block: 'center', behavior: 'smooth'}); el.classList.add('cm-flash'); setTimeout(() => el.classList.remove('cm-flash'), 1600);
  }

  /* ---------- inbox ---------- */
  async function loadInbox() {
    try { inbox = await api('/api/messages'); renderTabs(); renderRows(); }
    catch (e) { rowsEl.replaceChildren(h('div', 'cm-err', `Couldn't load conversations (${e.status || 'network'}): ${e.message}`)); }
  }
  function renderTabs() {
    $('cm-tabs').replaceChildren(...[['all', 'All', 0], ['unread', 'Unread', inbox.unread_conversations], ['requests', 'Requests', inbox.pending_requests]].map(([k, l, n]) => {
      const b = btn('cm-tab' + (tab === k ? ' on' : '')); b.append(h('span', '', l)); if (n) b.append(h('span', 'cm-n', n)); b.onclick = () => { tab = k; renderTabs(); renderRows(); }; return b;
    }));
  }
  function renderRows() {
    const s = q.toLowerCase();
    const items = (inbox.items || []).filter(c => (tab === 'all' || (tab === 'unread' && c.unread > 0) || (tab === 'requests' && c.is_request)) && (!s || (nameOf(c.other) + ' ' + c.other.username + ' ' + (c.preview || '')).toLowerCase().includes(s)));
    if (!items.length) { rowsEl.replaceChildren(h('div', 'cm-empty', s ? 'No matches' : tab === 'all' ? 'No conversations yet. Tap the pencil to start one.' : 'Nothing here')); return; }
    rowsEl.replaceChildren(...items.map(c => {
      // A wrapper, not a row with a button inside it: a <button> nested in a
      // <button> is invalid HTML and browsers flatten it, so the ⋮ would stop
      // working the moment it mattered. The row stays a button; the menu button
      // is its sibling and stops propagation.
      const wrap = h('div', 'cm-rwrap');
      const r = btn('cm-row' + (c.unread ? ' un' : '') + (c.other.username === active ? ' on' : ''));
      const m = h('div', 'cm-rm'), l1 = h('div', 'cm-l'), l2 = h('div', 'cm-l');
      l1.append(h('span', 'cm-nm', nameOf(c.other)), h('span', 'cm-tm', c.time_label || ''));
      l2.append(h('span', 'cm-pv', c.preview ? (c.preview_is_mine ? 'You: ' : '') + c.preview : (c.is_request ? 'Message request' : '')));
      if (c.unread > 0) l2.append(h('span', 'cm-n', c.unread)); else if (c.is_request) l2.append(h('span', 'cm-chip', 'Request'));
      m.append(l1, l2); r.append(avatar(c.other, 52), m); r.onclick = () => openThread(c.other.username);
      const more = btn('cm-more', 'Chat options for ' + nameOf(c.other));
      more.append(ico('more_horiz'));
      more.onclick = e => { e.stopPropagation(); rowMenu(c, more); };
      wrap.append(r, more);
      return wrap;
    }));
  }
  $('cm-q').oninput = e => { q = e.target.value; renderRows(); };

  /* ---------- thread ---------- */
  async function openThread(handle) {
    active = handle; thread = null; deal = {product: null}; renderBar(); pins = {list: [], ids: new Set(), max: 5}; wp = {kind: 'preset', preset: 'default', image_url: null, focus_x: .5, focus_y: .5, dim: 0, scope: 'none'};
    search = {on: false, q: '', hits: 0, i: 0}; $('cm-sbar').hidden = true; clearPending(); setReply(null); closeMenu(); infoTab = 'media';
    root.classList.add('open'); $('cm-blank').hidden = true; $('cm-view').hidden = false; note.textContent = '';
    msgsEl.replaceChildren(h('div', 'cm-empty', 'Loading…')); applyWp();
    history.replaceState(null, '', '/messages/@' + handle); renderRows();
    await loadThread(handle, true); if (matchMedia('(min-width:1024px)').matches) input.focus();
  }
  async function loadThread(handle, first) {
    try {
      const t = await api('/api/messages/threads/' + enc(handle)); if (active !== handle) return;
      thread = t; renderThread(first); if (first) loadWallpaper(); loadPins(); loadDeal(); if (infoOpen) renderInfo();
      if (t.unread > 0 && t.conversation) api(`/api/messages/${t.conversation.public_id}/read`, 'POST').then(loadInbox).catch(() => {});
    } catch (e) { if (active === handle) msgsEl.replaceChildren(h('div', 'cm-err', `Couldn't open this chat (${e.status || 'network'}): ${e.message}`)); }
  }
  function countHits(msgs, sq) { if (!sq) return 0; let n = 0; for (const m of msgs) { const low = (m.body || '').toLowerCase(); let i = 0, j; while ((j = low.indexOf(sq, i)) > -1) { n++; i = j + sq.length; } } return n; }
  function bindMsg(el, m) {
    let tm; el.addEventListener('contextmenu', e => { e.preventDefault(); msgMenu(m, el); });
    el.addEventListener('touchstart', () => { tm = setTimeout(() => msgMenu(m, el), 480); }, {passive: true});
    ['touchend', 'touchmove', 'touchcancel'].forEach(ev => el.addEventListener(ev, () => clearTimeout(tm), {passive: true}));
    el.addEventListener('click', e => { if (e.target.closest('a,img,button')) return; e.stopPropagation(); msgMenu(m, el); });
  }
  function renderThread(first) {
    const t = thread, u = t.other, typing = Date.now() < typingUntil, live = online.has(u.username) || t.is_active_now, msgs = t.messages || [];
    $('cm-hav').replaceChildren(avatar(u, 44)); $('cm-hname').textContent = nameOf(u);
    const hs = $('cm-hsub'); hs.textContent = typing ? 'typing…' : live ? 'Active now' : (t.last_seen_label || '@' + u.username); hs.className = 'cm-sub' + (typing || live ? ' live' : '');
    const tm = $('cm-timer'); tm.hidden = !t.conversation; if (t.conversation) $('cm-timer-t').textContent = t.conversation.disappearing === false ? 'Off' : '48h';
    $('cm-banner').hidden = !(t.is_incoming_request && t.conversation);
    const sq = search.on ? search.q.trim().toLowerCase() : '';
    search.hits = countHits(msgs, sq); if (search.i >= search.hits) search.i = 0; let seq = 0;
    const hl = text => { if (!sq) return [document.createTextNode(text)]; const out = [], low = text.toLowerCase(); let i = 0, j; while ((j = low.indexOf(sq, i)) > -1) { if (j > i) out.push(document.createTextNode(text.slice(i, j))); out.push(h('mark', seq === search.i ? 'cur' : '', text.slice(j, j + sq.length))); seq++; i = j + sq.length; } if (i < text.length) out.push(document.createTextNode(text.slice(i))); return out; };
    $('cm-scount').textContent = sq ? (search.hits ? `${search.i + 1} of ${search.hits}` : 'No results') : '';
    const nodes = []; let prevDay = '';
    msgs.forEach((m, i) => {
      const d = new Date(m.sent_at), dk = d.toDateString();
      if (dk !== prevDay) { nodes.push(h('div', 'cm-day', dayLabel(d))); prevDay = dk; }
      const nx = msgs[i + 1], tail = !nx || nx.is_mine !== m.is_mine || new Date(nx.sent_at).toDateString() !== dk;
      const ph = photoOf(m), pinned = pins.ids.has(m.public_id), row = h('div', 'cm-m ' + (m.is_mine ? 'me' : 'th')), b = h('div', 'cm-b' + (tail ? ' tail' : '') + (ph ? ' img' : '') + (pinned ? ' pinned' : '') + (m.kind === 'offer' ? ' offer' : ''));
      row.dataset.id = m.public_id;
      if (pinned) { const pb = h('span', 'cm-pinb'); pb.append(ico('push_pin')); b.append(pb); }
      if (m.reply_public_id) b.append(quoteEl(m));
      if (ph) { const im = h('img', 'cm-img'); im.src = ph; im.alt = 'Photo'; im.loading = 'lazy'; im.onclick = () => lightbox(ph); b.append(im); }
      if (m.kind === 'shared_product' && m.shared_product_slug) { const a = h('a', 'cm-share'); a.href = '/product/' + enc(m.shared_product_slug); a.append(ico('sell'), h('span', '', 'Shared a product')); b.append(a); }
      if (m.kind === 'shared_profile') { const hd = m.shared_user && m.shared_user.username; if (hd) { const a = h('a', 'cm-share'); a.href = '/@' + hd; a.append(ico('person'), h('span', '', 'Shared @' + hd)); b.append(a); } }
      if (m.kind === 'offer') b.append(offerCard(m)); else if (m.body) { const s = h('span', 'cm-t'); s.append(...hl(m.body)); b.append(s); }
      const ti = h('span', 'cm-time', tfmt(d)); ti.title = m.exact_time || ''; b.append(ti);
      if (m.reactions && m.reactions.length) {
        // Chips live inside the bubble's column so they line up under the tail
        // instead of floating in the middle of the thread.
        const rx = h('div', 'cm-rx');
        m.reactions.forEach(r => {
          const c = btn('cm-rxc' + (r.mine ? ' mine' : ''), `React ${r.emoji}`);
          c.append(document.createTextNode(r.emoji));
          if (r.count > 1) c.append(h('span', 'n', String(r.count)));
          c.onclick = e => { e.stopPropagation(); reactTo(m, r.emoji); };
          rx.append(c);
        });
        b.append(rx);
      }
      bindMsg(b, m); row.append(b); nodes.push(row);
    });
    if (!msgs.length) nodes.push(h('div', 'cm-empty', 'Say hello to ' + nameOf(u)));
    const last = msgs[msgs.length - 1];
    if (last && last.is_mine) { const rd = t.their_last_read_at ? new Date(t.their_last_read_at) : null; nodes.push(h('div', 'cm-seen', rd && rd >= new Date(last.sent_at) ? 'Seen · ' + tfmt(rd) : 'Sent')); }
    if (typing) { const tp = h('div', 'cm-typing'); tp.append(h('i'), h('i'), h('i')); nodes.push(tp); }
    const near = first || msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 140;
    msgsEl.replaceChildren(...nodes);
    const cur = sq && msgsEl.querySelector('mark.cur');
    if (cur) cur.scrollIntoView({block: 'center'}); else if (near) msgsEl.scrollTop = msgsEl.scrollHeight;
    const can = !!t.can_send; input.disabled = !can; $('cm-act').disabled = !can; note.textContent = can ? '' : (t.blocked_reason || "You can't send messages in this conversation.");
  }
  msgsEl.addEventListener('scroll', () => { $('cm-downbtn').hidden = msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 220; });
  $('cm-downbtn').onclick = () => msgsEl.scrollTo({top: msgsEl.scrollHeight, behavior: 'smooth'});
  function closeThread() { active = null; thread = null; deal = {product: null}; renderBar(); infoOpen = false; info.hidden = true; closeMenu(); root.classList.remove('open'); $('cm-view').hidden = true; $('cm-blank').hidden = false; history.replaceState(null, '', '/messages'); renderRows(); }
  $('cm-back').onclick = closeThread;

  /* ---------- search in chat ---------- */
  function openSearch() { search.on = true; $('cm-sbar').hidden = false; $('cm-sq').focus(); }
  function step(d) { if (!search.hits) return; search.i = (search.i + d + search.hits) % search.hits; renderThread(false); }
  $('cm-search').onclick = openSearch;
  $('cm-sq').oninput = e => { search.q = e.target.value; search.i = 0; if (thread) renderThread(false); };
  $('cm-sq').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); step(e.shiftKey ? -1 : 1); } };
  $('cm-sup').onclick = () => step(-1); $('cm-sdown').onclick = () => step(1);
  $('cm-sclose').onclick = () => { search = {on: false, q: '', hits: 0, i: 0}; $('cm-sq').value = ''; $('cm-sbar').hidden = true; if (thread) renderThread(false); };

  /* ---------- composer: mic turns into send ---------- */
  const hasContent = () => !!(input.value.trim() || pending);
  function syncAct() { const b = $('cm-act'), on = hasContent(); b.replaceChildren(ico(on ? 'send' : 'mic')); b.type = on ? 'submit' : 'button'; b.setAttribute('aria-label', on ? 'Send' : 'Voice note'); }
  $('cm-act').onclick = e => { if (!hasContent()) { e.preventDefault(); toast('Voice notes are coming in a later update'); } };
  input.addEventListener('input', () => {
    input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 128) + 'px'; syncAct();
    const now = Date.now(); if (ws && ws.readyState === 1 && thread && thread.conversation && now - lastTyping > 3000) { lastTyping = now; ws.send(JSON.stringify({type: 'typing', conversation: thread.conversation.public_id, state: 'start'})); }
  });
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && matchMedia('(min-width:1024px)').matches) { e.preventDefault(); $('cm-form').requestSubmit(); } });
  function clearPending() { if (pending) URL.revokeObjectURL(pending.url); pending = null; $('cm-tray').hidden = true; syncAct(); }
  function pick(f) { if (!f) return; if (!f.type.startsWith('image/')) { toast('Only photos can be sent for now'); return; } clearPending(); pending = {file: f, url: URL.createObjectURL(f)}; $('cm-trayimg').src = pending.url; $('cm-traysz').textContent = (f.size / 1048576).toFixed(1) + ' MB · add a caption if you like'; $('cm-tray').hidden = false; syncAct(); input.focus(); }
  $('cm-cam').onclick = () => $('cm-filecam').click(); $('cm-clip').onclick = () => $('cm-file').click();
  $('cm-file').onchange = e => { pick(e.target.files[0]); e.target.value = ''; }; $('cm-filecam').onchange = e => { pick(e.target.files[0]); e.target.value = ''; };
  $('cm-trayx').onclick = clearPending;
  $('cm-reply-x').onclick = () => setReply(null);
  const emo = $('cm-emoji'); EMOJI.forEach(x => { const b = btn('', ''); b.textContent = x; b.onclick = () => { const a = input.selectionStart ?? input.value.length, z = input.selectionEnd ?? a; input.setRangeText(x, a, z, 'end'); input.dispatchEvent(new Event('input')); input.focus(); }; emo.append(b); });
  $('cm-emo').onclick = e => { e.stopPropagation(); emo.hidden = !emo.hidden; };
  document.addEventListener('click', e => { if (!emo.contains(e.target)) emo.hidden = true; closeMenu(); });
  $('cm-form').onsubmit = async ev => {
    ev.preventDefault(); const body = input.value.trim(); if ((!body && !pending) || !active || !thread || !thread.can_send) return;
    $('cm-act').disabled = true; note.textContent = '';
    try {
      if (pending) { const fd = new FormData(); fd.append('file', pending.file); if (body) fd.append('body', body); await api(`/api/messages/threads/${enc(active)}/photo`, 'POST', fd); }
      else await api('/api/messages/threads/' + enc(active), 'POST', {kind: 'text', body, reply_to: replyTo ? replyTo.public_id : null});
      input.value = ''; input.style.height = ''; clearPending(); setReply(null); await loadThread(active, true); loadInbox();
    } catch (e) { note.textContent = e.message; }
    $('cm-act').disabled = false; syncAct(); input.focus();
  };

  /* ---------- request actions, timer ---------- */
  async function act(path) { try { await api(path, 'POST'); await loadThread(active, false); loadInbox(); } catch (e) { note.textContent = e.message; } }
  $('cm-accept').onclick = () => act(`/api/messages/${thread.conversation.public_id}/accept`);
  $('cm-decline').onclick = async () => { await act(`/api/messages/${thread.conversation.public_id}/decline`); closeThread(); };
  async function toggleTimer() { if (!thread || !thread.conversation) return; const on = thread.conversation.disappearing === false; try { await api(`/api/messages/${thread.conversation.public_id}/disappearing`, 'PATCH', {enabled: on}); toast(on ? 'Disappearing messages on (48 hours)' : 'Disappearing messages off'); await loadThread(active, false); } catch (e) { toast(e.message); } }
  $('cm-timer').onclick = toggleTimer;

  /* ---------- contact info ---------- */
  $('cm-infobtn').onclick = () => { infoOpen = !infoOpen; info.hidden = !infoOpen; if (infoOpen) renderInfo(); };
  function pinnedList(u) {
    const box = h('div', '', ''); box.style.cssText = 'display:flex;flex-direction:column;flex:1';
    if (!pins.list.length) { const e = h('div', 'cm-empty', 'No pinned messages yet. Tap a message and choose Pin.'); e.style.padding = '28px 20px'; box.append(e); }
    pins.list.forEach(p => {
      const m = p.message, who = m.is_mine ? {username: D.me, display_name: 'You'} : u, d = new Date(m.sent_at), it = btn('cm-pi'), top = h('div', 'cm-pit'), body = h('div', 'cm-pib');
      top.append(avatar(who, 26), h('b', '', m.is_mine ? 'You' : nameOf(u)), h('span', 'cm-tm', dayLabel(d) + ', ' + tfmt(d)), ico('push_pin'));
      const ph = photoOf(m); if (ph) { const im = h('img'); im.src = ph; im.alt = 'Photo'; body.append(im); } if (m.body) body.append(h('div', '', m.body)); if (!ph && !m.body) body.append('Message');
      it.append(top, body); it.onclick = () => jumpTo(m.public_id); box.append(it);
    });
    const hint = h('div', 'cm-hint'); hint.append(ico('push_pin'), h('span', '', `You can pin up to ${pins.max} messages. Unpin one to make room for another.`)); box.append(hint); return box;
  }
  function renderInfo() {
    const t = thread; if (!t) return; const u = t.other, nodes = [];
    const hd = h('div', 'cm-ihead'); hd.append(h('span', '', 'Contact info')); const x = btn('cm-ib sm', 'Close'); x.append(ico('close')); x.onclick = () => { infoOpen = false; info.hidden = true; }; hd.append(x); nodes.push(hd);
    const top = h('div', 'cm-top'); const nm = h('div', '', nameOf(u)); nm.style.cssText = 'font-size:20px;font-weight:800;margin-bottom:2px'; top.append(avatar(u, 88), nm, h('div', 'cm-sub', '@' + u.username)); nodes.push(top);
    const acts = h('div', 'cm-acts'); const a1 = btn('cm-act'); const b1 = h('span', 'cm-ib'); b1.append(ico('search')); a1.append(b1, 'Search'); a1.onclick = () => { if (matchMedia('(max-width:1023px)').matches) { infoOpen = false; info.hidden = true; } openSearch(); };
    const a2 = h('a', 'cm-act'); a2.href = '/@' + u.username; const b2 = h('span', 'cm-ib'); b2.append(ico('person')); a2.append(b2, 'Profile'); acts.append(a1, a2); nodes.push(acts);
    const w = btn('cm-set'); const sw = h('span', 'cm-sw'); paintWp(sw, wp); const label = wp.kind === 'photo' ? 'Photo' : (WPS.find(z => z[0] === wp.preset) || WPS[0])[1];
    w.append(sw, h('span', 'sp', 'Chat wallpaper'), h('small', '', label), ico('chevron_right')); w.onclick = openWallpaper; nodes.push(w);
    if (t.conversation) { const pr = btn('cm-set'); pr.append(ico('sell'), h('span', 'sp', 'Pinned product'), h('small', '', deal.product ? deal.product.name : 'None'), ico('chevron_right')); pr.onclick = openProductPicker; nodes.push(pr); }
    const imgs = (t.messages || []).map(photoOf).filter(Boolean);
    const tabs = h('div', 'cm-itabs'); [['media', `Media${imgs.length ? ' ' + imgs.length : ''}`], ['pinned', `Pinned ${pins.list.length}/${pins.max}`]].forEach(([k, l]) => { const b = btn(infoTab === k ? 'on' : '', ''); b.textContent = l; b.onclick = () => { infoTab = k; renderInfo(); }; tabs.append(b); }); nodes.push(tabs);
    if (infoTab === 'pinned') nodes.push(pinnedList(u));
    else if (imgs.length) { const g = h('div', 'cm-grid'); g.style.paddingTop = '3px'; imgs.slice().reverse().forEach(s => { const i = h('img'); i.src = s; i.alt = 'Photo'; i.loading = 'lazy'; i.onclick = () => lightbox(s); g.append(i); }); nodes.push(g); }
    else { const e = h('div', 'cm-empty', 'Photos from this chat appear here.'); e.style.padding = '28px 20px'; nodes.push(e); }
    const foot = h('div'); foot.style.marginTop = 'auto';
    if (t.conversation) {
      const on = t.conversation.disappearing !== false, tr = btn('cm-set'); tr.append(ico('timer'), h('span', 'sp', 'Disappearing messages'), h('span', 'cm-tog' + (on ? ' on' : ''))); tr.onclick = toggleTimer; foot.append(tr);
      const ar = btn('cm-set'); ar.append(ico('archive'), h('span', 'sp', 'Archive chat')); ar.onclick = async () => { try { await api(`/api/messages/${t.conversation.public_id}/archive`, 'POST'); closeThread(); loadInbox(); } catch (e) { toast(e.message); } }; foot.append(ar);
    }
    const bl = btn('cm-set red'); bl.append(ico('block'), h('span', 'sp', 'Block ' + nameOf(u))); bl.onclick = async () => { if (!confirm(`Block @${u.username}? You won't see each other's messages.`)) return; try { await api('/api/messages/blocks/' + enc(u.username), 'POST'); closeThread(); loadInbox(); } catch (e) { toast(e.message); } }; foot.append(bl);
    const rp = btn('cm-set red'); rp.append(ico('flag'), h('span', 'sp', 'Report')); rp.onclick = openReport; foot.append(rp); nodes.push(foot);
    info.replaceChildren(...nodes);
  }
  function openReport() {
    const u = thread.other; let pick = null;
    sheet('Report ' + nameOf(u), (s, close) => {
      const list = h('div'), noteEl = h('textarea'); noteEl.rows = 3; noteEl.placeholder = 'Add a note (optional)'; const err = h('div', 'cm-note');
      reasons.forEach(r => { const v = Array.isArray(r) ? r[0] : (r && typeof r === 'object' ? (r.value ?? r.key ?? r.id) : r), l = Array.isArray(r) ? r[1] : (r && typeof r === 'object' ? (r.label ?? r.name ?? v) : r); const b = btn('cm-opt'); b.append(ico('radio_button_unchecked'), h('span', '', String(l))); b.onclick = () => { pick = v; list.querySelectorAll('.cm-opt').forEach(z => { z.classList.remove('on'); z.firstChild.textContent = 'radio_button_unchecked'; }); b.classList.add('on'); b.firstChild.textContent = 'radio_button_checked'; }; list.append(b); });
      const go = btn('cm-btn p'); go.textContent = 'Send report'; go.onclick = async () => { if (!pick) { err.textContent = 'Choose a reason first.'; return; } try { await api('/api/messages/reports/' + enc(u.username), 'POST', {reason: pick, note: noteEl.value.trim() || null, conversation_public_id: thread.conversation ? thread.conversation.public_id : null}); close(); toast('Report sent. Thank you.'); } catch (e) { err.textContent = e.message; } };
      s.append(list, noteEl, err, go);
    });
  }

  /* ---------- wallpaper picker + crop ---------- */
  function openWallpaper() {
    const hasConv = !!(thread && thread.conversation);
    let preset = wp.kind === 'preset' ? wp.preset : 'default', scope = hasConv ? 'chat' : 'all', dim = wp.dim || 0, photo = null;
    sheet('Chat wallpaper', (s, close) => {
      const body = h('div'); s.append(body);
      const errEl = h('div', 'cm-note');
      function main() {
        const prev = h('div', 'cm-prev'); if (photo) paintWp(prev, {kind: 'photo', image_url: photo.url, dim}); else paintWp(prev, {kind: 'preset', preset});
        const r1 = h('div', 'cm-m th'), r2 = h('div', 'cm-m me'); r1.append(h('div', 'cm-b tail', 'Is the blue tote still available?')); r2.append(h('div', 'cm-b tail', 'Yes it is, in stock.')); prev.append(r1, r2);
        const nodes = [prev];
        const seg = h('div', 'cm-seg'); [['chat', 'This chat'], ['all', 'All chats']].forEach(([k, l]) => { const b = btn(k === scope ? 'on' : ''); b.textContent = l; if (k === 'chat' && !hasConv) { b.disabled = true; b.title = 'Send a first message to set a wallpaper for this chat only'; b.style.opacity = '.45'; } b.onclick = () => { scope = k; seg.querySelectorAll('button').forEach(z => z.classList.toggle('on', z === b)); }; seg.append(b); }); nodes.push(seg);
        const grid = h('div', 'cm-sws'); WPS.forEach(([k, l]) => { const b = btn('cm-swb' + (!photo && k === preset ? ' on' : '')); b.append(h('i', 'wp-' + k), l); b.onclick = () => { photo = null; preset = k; main(); }; grid.append(b); }); nodes.push(grid);
        const pb = btn('cm-set'); pb.style.cssText += ';margin-top:12px;border-radius:14px;border:1px solid var(--line)'; pb.append(ico('photo_library'), h('span', 'sp', photo ? 'Choose a different photo' : 'Choose from photos'), ico('chevron_right'));
        const fi = h('input'); fi.type = 'file'; fi.accept = 'image/*'; fi.hidden = true; fi.onchange = e => { const f = e.target.files[0]; if (f) crop(f); }; pb.onclick = () => fi.click(); nodes.push(pb, fi);
        if (photo) { const row = h('div'); row.style.cssText = 'display:flex;align-items:center;gap:14px;padding:12px 4px 0'; const rg = h('input', 'cm-range'); rg.type = 'range'; rg.min = 0; rg.max = 60; rg.value = dim; rg.oninput = () => { dim = +rg.value; paintWp(prev, {kind: 'photo', image_url: photo.url, dim}); }; const lb = h('b', '', 'Dim'); lb.style.fontSize = '14px'; row.append(lb, rg); nodes.push(row); }
        const set = btn('cm-btn p'); set.style.marginTop = '14px'; set.textContent = 'Set wallpaper';
        set.onclick = async () => {
          set.disabled = true; errEl.textContent = '';
          try {
            const c = thread.conversation ? thread.conversation.public_id : null;
            if (photo) { const fd = new FormData(); fd.append('file', photo.blob, 'wallpaper.jpg'); fd.append('scope', scope); if (scope === 'chat') fd.append('conversation', c); fd.append('ratio', photo.ratio); fd.append('dim', dim); wp = await api('/api/messages/wallpaper/photo', 'POST', fd); }
            else wp = await api('/api/messages/wallpaper', 'PUT', {scope, conversation: scope === 'chat' ? c : null, preset, dim: 0});
            applyWp(); close(); if (infoOpen) renderInfo(); toast('Wallpaper set');
          } catch (e) { errEl.textContent = e.message; set.disabled = false; }
        };
        nodes.push(errEl, set);
        if (wp.scope !== 'none') { const rs = btn('cm-btn'); rs.style.marginTop = '8px'; rs.textContent = 'Remove ' + (wp.scope === 'chat' ? 'this chat’s' : 'my default') + ' wallpaper'; rs.onclick = async () => { try { await api(`/api/messages/wallpaper?scope=${wp.scope}` + (wp.scope === 'chat' && thread.conversation ? '&conversation=' + thread.conversation.public_id : ''), 'DELETE'); await loadWallpaper(); close(); toast('Wallpaper removed'); } catch (e) { errEl.textContent = e.message; } }; nodes.push(rs); }
        body.replaceChildren(...nodes);
      }
      function crop(file) {
        const url = URL.createObjectURL(file), img = new Image(); let ri = 0, nw = 0, nh = 0, sc = 1, off = {x: 0, y: 0}, S = {w: 0, h: 0}, drag = null;
        const BOX = 330, PANE = 1.3;
        const stage = h('div', 'cm-stage'), thirds = h('div', 'cm-thirds'), safe = h('div', 'cm-safe'), tag = h('span', '', 'Always visible'); safe.append(tag); stage.append(thirds, safe);
        const sw = h('div', 'cm-stagewrap'); sw.append(stage);
        const chips = h('div', 'cm-ratios'); RATIOS.forEach(([k, , l], i) => { const b = btn(i === ri ? 'on' : ''); b.append(h('span', '', l)); b.onclick = () => { ri = i; chips.querySelectorAll('button').forEach((z, j) => z.classList.toggle('on', j === i)); layout(true); }; chips.append(b); });
        const clamp = () => { off.x = Math.min(0, Math.max(S.w - nw * sc, off.x)); off.y = Math.min(0, Math.max(S.h - nh * sc, off.y)); };
        const paint = () => { stage.style.backgroundPosition = `${off.x}px ${off.y}px`; };
        function layout(center) {
          const r = RATIOS[ri][1]; S.w = Math.round(r >= 1 ? BOX : BOX * r); S.h = Math.round(r >= 1 ? BOX / r : BOX);
          stage.style.width = S.w + 'px'; stage.style.height = S.h + 'px'; sc = Math.max(S.w / nw, S.h / nh); stage.style.backgroundSize = `${nw * sc}px ${nh * sc}px`;
          if (center) { off.x = (S.w - nw * sc) / 2; off.y = (S.h - nh * sc) / 2; } clamp(); paint();
          if (r < PANE) { const f = r / PANE; Object.assign(safe.style, {left: '0', right: '0', width: '', top: (50 - f * 50) + '%', height: f * 100 + '%'}); }
          else { const f = PANE / r; Object.assign(safe.style, {top: '0', bottom: '0', height: '', left: (50 - f * 50) + '%', width: f * 100 + '%'}); }
        }
        stage.style.backgroundImage = `url("${url}")`;
        stage.onpointerdown = e => { drag = {x: e.clientX, y: e.clientY, ox: off.x, oy: off.y}; stage.setPointerCapture(e.pointerId); };
        stage.onpointermove = e => { if (!drag) return; off.x = drag.ox + e.clientX - drag.x; off.y = drag.oy + e.clientY - drag.y; clamp(); paint(); };
        stage.onpointerup = stage.onpointercancel = () => { drag = null; };
        const tip = h('div', 'cm-sub', 'Drag the photo to frame it. Keep faces and text inside the dashed zone: wider screens show a shorter slice.'); tip.style.cssText = 'text-align:center;margin:4px 0 10px;white-space:normal';
        const row = h('div'); row.style.cssText = 'display:flex;gap:10px'; const cancel = btn('cm-btn'); cancel.textContent = 'Cancel'; const done = btn('cm-btn p'); done.textContent = 'Use photo'; done.style.flex = '2'; cancel.style.flex = '1'; row.append(cancel, done);
        cancel.onclick = () => { URL.revokeObjectURL(url); main(); };
        done.onclick = () => {
          const r = RATIOS[ri][1], cw = Math.round(r >= 1 ? 1600 : 1600 * r), ch = Math.round(r >= 1 ? 1600 / r : 1600), cv = document.createElement('canvas'); cv.width = cw; cv.height = ch;
          cv.getContext('2d').drawImage(img, -off.x / sc, -off.y / sc, S.w / sc, S.h / sc, 0, 0, cw, ch);
          cv.toBlob(b => { if (!b) { toast("Couldn't prepare that photo"); return; } URL.revokeObjectURL(url); photo = {blob: b, url: URL.createObjectURL(b), ratio: RATIOS[ri][0]}; main(); }, 'image/jpeg', .86);
        };
        img.onload = () => { nw = img.naturalWidth; nh = img.naturalHeight; layout(true); };
        img.onerror = () => { URL.revokeObjectURL(url); toast("This photo format can't be previewed here. Try a JPG or PNG."); main(); };
        img.src = url; body.replaceChildren(sw, chips, tip, row);
      }
      main();
    });
  }

  /* ---------- pinned product + offers ---------- */
  const naira = n => '₦' + Number(n || 0).toLocaleString('en-NG');
  const bar = h('div', 'cm-bar'); bar.hidden = true; wrapEl.parentElement.insertBefore(bar, wrapEl);
  const OFFER_LABEL = {accepted: 'Accepted', countered: 'Countered', declined: 'Declined', withdrawn: 'Cancelled'};
  const dealUrl = p => `/api/messages/${thread.conversation.public_id}${p}`;

  async function loadDeal() {
    const c = thread && thread.conversation;
    if (!c) { deal = {product: null}; renderBar(); return; }
    try {
      const d = await api(`/api/messages/${c.public_id}/deal`);
      if (!thread || !thread.conversation || thread.conversation.public_id !== c.public_id) return;
      deal = d;
    } catch { return; }
    renderBar(); if (infoOpen) renderInfo();
  }

  function priceSheet(title, listed, label, onSend) {
    sheet(title, (s, close) => {
      const hint = h('div', 'cm-sub', 'Listed at ' + naira(listed)); hint.style.cssText = 'white-space:normal;margin:0 0 10px';
      const inp = h('input'); inp.type = 'number'; inp.inputMode = 'numeric'; inp.min = 1; inp.max = listed; inp.placeholder = 'Amount in ₦'; inp.autocomplete = 'off';
      const err = h('div', 'cm-note'), go = btn('cm-btn p'); go.textContent = label; go.style.marginTop = '12px';
      go.onclick = async () => {
        const v = Math.round(Number(inp.value));
        if (!(v > 0)) { err.textContent = 'Enter an amount above ₦0.'; return; }
        if (v > listed) { err.textContent = `An offer can't be above the listed ${naira(listed)}.`; return; }
        go.disabled = true; err.textContent = '';
        try { await onSend(v); close(); } catch (e) { err.textContent = e.message; go.disabled = false; }
      };
      s.append(hint, inp, err, go); setTimeout(() => inp.focus(), 60);
    });
  }

  function renderBar() {
    const p = deal.product;
    if (!p || !thread || !thread.conversation) { bar.hidden = true; bar.replaceChildren(); return; }
    bar.hidden = false;
    const a = h('a', 'cm-bp'); a.href = '/product/' + enc(p.slug);
    const im = h('span', 'cm-bi'); if (p.image_url) { const i = h('img'); i.src = p.image_url; i.alt = ''; im.append(i); } else im.append(ico('sell'));
    const tx = h('span', 'cm-bt'); tx.append(h('b', '', p.name), h('small', '', deal.sold ? 'Sold' : [p.price_label, p.stock_label].filter(Boolean).join(' · ')));
    a.append(im, tx);
    const nodes = [a];
    if (deal.seller_is_me) {
      const b = btn('cm-bb' + (deal.sold ? '' : ' p')); b.textContent = deal.sold ? 'Mark as available' : 'Mark as sold';
      b.onclick = async () => { b.disabled = true; try { deal = await api(dealUrl('/product/sold'), 'POST', {sold: !deal.sold}); renderBar(); loadThread(active, false); } catch (e) { toast(e.message); b.disabled = false; } };
      nodes.push(b);
    } else if (deal.can_offer) {
      const b = btn('cm-bb o'); b.append(ico('sell'), h('span', '', 'Make an offer'));
      b.onclick = () => priceSheet('Make an offer', p.price, 'Send offer', async v => { deal = await api(dealUrl('/offers'), 'POST', {price: v}); renderBar(); await loadThread(active, false); loadInbox(); });
      nodes.push(b);
    } else {
      const t = deal.sold ? 'Sold' : deal.pending_offer ? 'Offer pending' : deal.accepted_offer ? 'Offer accepted' : !p.in_stock ? 'Out of stock' : '';
      if (t) nodes.push(h('span', 'cm-bchip', t));
    }
    bar.replaceChildren(...nodes);
  }

  async function offerCall(m, action, price) {
    await api(dealUrl('/offers/' + m.public_id), 'POST', {action, price: price ?? null});
    await loadThread(active, false); loadInbox();
  }
  function offerCard(m) {
    const st = m.offer_status || 'pending', c = h('div', 'cm-offer'), top = h('div', 'cm-ot'), ic = h('span', 'cm-oi'); ic.append(ico('sell'));
    top.append(ic, h('span', 'cm-ol', m.is_mine ? 'You offered' : 'Offer'));
    const foot = h('div', 'cm-of'); foot.append(h('span', 'cm-os ' + st, st === 'pending' ? (m.is_mine ? 'Waiting for reply' : 'Needs your reply') : (OFFER_LABEL[st] || st)));
    c.append(top, h('div', 'cm-op', naira(m.offer_price)), h('div', 'cm-ls', 'Listed at ' + naira(m.offer_listed)), foot);
    if (st === 'pending') {
      const row = h('div', 'cm-oa');
      const mk = (label, cls, fn) => { const b = btn('cm-ob ' + cls); b.textContent = label; b.onclick = async e => { e.stopPropagation(); b.disabled = true; try { await fn(); } catch (err) { toast(err.message); b.disabled = false; } }; row.append(b); };
      if (m.is_mine) mk('Cancel offer', '', () => offerCall(m, 'withdraw'));
      else {
        mk('Accept', 'p', () => offerCall(m, 'accept'));
        const cb = btn('cm-ob'); cb.textContent = 'Counter'; cb.onclick = e => { e.stopPropagation(); priceSheet('Counter offer', m.offer_listed, 'Send counter', v => offerCall(m, 'counter', v)); }; row.append(cb);
        mk('Decline', 'd', () => offerCall(m, 'decline'));
      }
      c.append(row);
    }
    return c;
  }

  async function openProductPicker() {
    if (!thread || !thread.conversation) { toast('Send a first message to pin a product to this chat'); return; }
    let role = 'buyer';
    sheet('Pinned product', async (s, close) => {
      if (!deal.product) {
        const seg = h('div', 'cm-seg');
        [['buyer', "I'm buying"], ['seller', "I'm selling"]].forEach(([k, l]) => { const b = btn(k === role ? 'on' : ''); b.textContent = l; b.onclick = () => { role = k; seg.querySelectorAll('button').forEach(z => z.classList.toggle('on', z === b)); }; seg.append(b); });
        s.append(seg);
      } else {
        const rm = btn('cm-btn'); rm.textContent = 'Remove pinned product'; rm.style.marginBottom = '10px';
        rm.onclick = async () => { try { deal = await api(dealUrl('/product'), 'DELETE'); renderBar(); if (infoOpen) renderInfo(); close(); } catch (e) { toast(e.message); } };
        s.append(rm);
      }
      const box = h('div'); box.append(h('div', 'cm-empty', 'Loading products…')); s.append(box);
      try {
        const d = await api('/api/messages/catalog/products');
        box.replaceChildren(...d.items.map(p => {
          const b = btn('cm-row'), im = h('span', 'cm-bi'), m = h('div', 'cm-rm');
          if (p.image_url) { const i = h('img'); i.src = p.image_url; i.alt = ''; im.append(i); } else im.append(ico('sell'));
          m.append(h('div', 'cm-nm', p.name), h('div', 'cm-sub', p.price_label + ' · ' + p.stock_label)); b.append(im, m);
          b.onclick = async () => { try { deal = await api(dealUrl('/product'), 'PUT', {slug: p.slug, role}); renderBar(); if (infoOpen) renderInfo(); close(); } catch (e) { toast(e.message); } };
          return b;
        }));
      } catch (e) { box.replaceChildren(h('div', 'cm-err', e.message)); }
    });
  }

  /* ---------- new message ---------- */
  async function openCompose() {
    sheet('New message', async (s, close) => {
      const f = h('form'), inp = h('input'); inp.type = 'text'; inp.placeholder = 'Type a username and press Enter'; inp.autocomplete = 'off'; f.append(inp);
      const box = h('div'); box.append(h('div', 'cm-empty', 'Loading people you follow…')); s.append(f, box); inp.focus();
      f.onsubmit = e => { e.preventDefault(); const v = inp.value.trim().replace(/^@/, ''); if (v) { close(); openThread(v); } };
      try {
        const d = await api('/api/messages/candidates'), arr = Array.isArray(d) ? d : (d.items || d.candidates || d.users || []);
        box.replaceChildren(...(arr.length ? arr.map(c => { const u = c.other || c.user || c, b = btn('cm-row'); const m = h('div', 'cm-rm'); m.append(h('div', 'cm-nm', nameOf(u)), h('div', 'cm-sub', '@' + u.username)); b.append(avatar(u, 44), m); b.onclick = () => { close(); openThread(u.username); }; return b; }) : [h('div', 'cm-empty', 'Follow someone to message them, or type a username above.')]));
      } catch { box.replaceChildren(); }
    });
  }
  $('cm-new').onclick = openCompose; $('cm-new2').onclick = openCompose;
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { layer.replaceChildren(); emo.hidden = true; closeMenu(); document.querySelectorAll('.cm-lb').forEach(x => x.remove()); } });

  /* ---------- live socket, polling fallback ---------- */
  let backoff = 1000, pingT = null, pollT = null, refT = null;
  const refresh = () => { clearTimeout(refT); refT = setTimeout(() => { loadInbox(); if (active) loadThread(active, false); }, 150); };
  function onFrame(f) {
    switch (f.type) {
      case 'ready': online = new Set(f.online || []); renderRows(); break;
      case 'presence': f.online ? online.add(f.username) : online.delete(f.username); if (thread) renderThread(false); renderRows(); break;
      case 'typing': if (thread && thread.conversation && f.conversation === thread.conversation.public_id) { typingUntil = f.state === 'stop' ? 0 : Date.now() + 4000; renderThread(false); setTimeout(() => thread && renderThread(false), 4100); } break;
      case 'pong': break;
      case 'pins': if (thread && thread.conversation && f.conversation === thread.conversation.public_id) loadPins(); break;
      default: refresh();
    }
  }
  function connect() {
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/messages`);
    ws.onopen = () => { backoff = 1000; clearInterval(pollT); pingT = setInterval(() => ws.readyState === 1 && ws.send('{"type":"ping"}'), 25000); refresh(); };
    ws.onmessage = e => { try { onFrame(JSON.parse(e.data)); } catch {} };
    ws.onclose = ev => { clearInterval(pingT); if (ev.code === 4401) return; clearInterval(pollT); pollT = setInterval(refresh, 15000); setTimeout(connect, backoff); backoff = Math.min(backoff * 2, 30000); };
  }

  /* ---------- boot ---------- */
  fit(); requestAnimationFrame(fit); setTimeout(fit, 300); syncAct(); applyWp(); renderTabs(); loadInbox(); connect();
  const target = D.shareUser || D.open;
  if (target) openThread(target).then(() => { if (D.shareSlug && !input.value) { input.value = location.origin + '/product/' + D.shareSlug; syncAct(); } });
})();
