(() => {
  'use strict';
  const root = document.getElementById('cm'); if (!root) return;
  const $ = id => document.getElementById(id), D = root.dataset;
  const shell = $('cm-shell'), rowsEl = $('cm-rows'), msgsEl = $('cm-msgs'), input = $('cm-input'), note = $('cm-note'), layer = $('cm-layer'), info = $('cm-info');
  const reasons = (() => { try { return JSON.parse($('cm-reasons').textContent) || []; } catch { return []; } })();
  const WPS = [['default','Default'],['dots','Dots'],['grid','Grid'],['lines','Lines'],['sky','Sky'],['mint','Mint'],['peach','Peach'],['lilac','Lilac']];
  const EMOJI = '😀 😂 😊 😍 🥰 😘 😎 🤩 🥳 😅 🤣 🙂 😉 😇 🤔 😮 😢 😭 😡 😴 🙏 👍 👎 👏 🙌 💪 🤝 👋 ❤️ 🔥 ✨ 🎉 💯 ✅ ❌ 👀 🎁 🛍️ 📦 💸 🏠 🎓 📚 ☕ 🍕 🚗 📍'.split(' ');
  let inbox = {items: [], unread_conversations: 0, pending_requests: 0}, tab = 'all', q = '', active = null, thread = null;
  let online = new Set(), typingUntil = 0, lastTyping = 0, ws = null, pending = null, infoOpen = false;
  let search = {on: false, q: '', hits: 0, i: 0};

  /* ---------- helpers ---------- */
  const h = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
  const ico = (n, c = '') => { const s = h('span', 'material-symbols-outlined ' + c, n); s.setAttribute('aria-hidden', 'true'); return s; };
  const enc = encodeURIComponent;
  const nameOf = u => u.display_name || u.name || u.full_name || u.username || '';
  const picOf = u => u.avatar_url || u.profile_image_url || u.avatar || u.image_url || null;
  const photoOf = m => m.photo_url || m.image_url || m.media_url || m.url || (m.media && (m.media.url || m.media.photo_url)) || null;
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
  let toastT; function toast(msg) { document.querySelectorAll('.cm-toast').forEach(e => e.remove()); const t = h('div', 'cm-toast', msg); document.body.append(t); clearTimeout(toastT); toastT = setTimeout(() => t.remove(), 2600); }
  function avatar(u, size) {
    const a = h('div', 'cm-av'); a.style.cssText = `width:${size}px;height:${size}px;font-size:${Math.round(size * .36)}px`;
    const p = picOf(u); if (p) { const i = h('img'); i.src = p; i.alt = ''; a.append(i); } else a.append((nameOf(u)[0] || '?').toUpperCase());
    if (online.has(u.username)) a.append(h('i')); return a;
  }
  function lightbox(src) { const l = h('div', 'cm-lb'); const i = h('img'); i.src = src; i.alt = 'Photo'; l.append(i); l.onclick = () => l.remove(); document.body.append(l); }
  function sheet(title, build) {
    const o = h('div', 'cm-over'), s = h('div', 'cm-sheet'), hd = h('h3', '', title), x = h('button', 'cm-ib sm'); x.type = 'button'; x.setAttribute('aria-label', 'Close'); x.append(ico('close'));
    const close = () => o.remove(); x.onclick = close; hd.append(x); s.append(hd); build(s, close); o.append(s); o.onclick = e => { if (e.target === o) close(); }; layer.append(o); return close;
  }

  /* ---------- fit to the screen ---------- */
  function fit() {
    const lg = matchMedia('(min-width:1024px)').matches, p = root.parentElement, cs = getComputedStyle(p);
    root.style.margin = `-${cs.paddingTop} -${cs.paddingRight} -${cs.paddingBottom} -${cs.paddingLeft}`;
    const top = root.getBoundingClientRect().top; let bottom = 0;
    if (!lg) for (const n of document.querySelectorAll('nav,footer')) { const r = n.getBoundingClientRect(); if (getComputedStyle(n).position === 'fixed' && r.top > innerHeight / 2 && r.height > 0) bottom = Math.max(bottom, innerHeight - r.top); }
    shell.style.height = Math.max(320, innerHeight - top - bottom) + 'px';
  }
  addEventListener('resize', fit);

  /* ---------- wallpapers (this device; synced to your account in the next step) ---------- */
  const WK = 'cf_wallpaper';
  const wpAll = () => { try { return JSON.parse(localStorage.getItem(WK)) || {}; } catch { return {}; } };
  const wpFor = u => { const p = wpAll(); return (u && p[u]) || p.all || 'default'; };
  function setWp(key, scope) { const p = wpAll(); if (scope === 'all') p.all = key; else p[active] = key; try { localStorage.setItem(WK, JSON.stringify(p)); } catch {} applyWp(); }
  function applyWp() { msgsEl.className = 'cm-msgs wp-' + wpFor(active); }

  /* ---------- inbox ---------- */
  async function loadInbox() {
    try { inbox = await api('/api/messages'); renderTabs(); renderRows(); }
    catch (e) { rowsEl.replaceChildren(h('div', 'cm-err', `Couldn't load conversations (${e.status || 'network'}): ${e.message}`)); }
  }
  function renderTabs() {
    $('cm-tabs').replaceChildren(...[['all', 'All', 0], ['unread', 'Unread', inbox.unread_conversations], ['requests', 'Requests', inbox.pending_requests]].map(([k, l, n]) => {
      const b = h('button', 'cm-tab' + (tab === k ? ' on' : '')); b.type = 'button'; b.append(h('span', '', l)); if (n) b.append(h('span', 'cm-n', n)); b.onclick = () => { tab = k; renderTabs(); renderRows(); }; return b;
    }));
  }
  function renderRows() {
    const s = q.toLowerCase();
    const items = (inbox.items || []).filter(c => (tab === 'all' || (tab === 'unread' && c.unread > 0) || (tab === 'requests' && c.is_request)) && (!s || (nameOf(c.other) + ' ' + c.other.username + ' ' + (c.preview || '')).toLowerCase().includes(s)));
    if (!items.length) { rowsEl.replaceChildren(h('div', 'cm-empty', s ? 'No matches' : tab === 'all' ? 'No conversations yet. Tap the pencil to start one.' : 'Nothing here')); return; }
    rowsEl.replaceChildren(...items.map(c => {
      const r = h('button', 'cm-row' + (c.unread ? ' un' : '') + (c.other.username === active ? ' on' : '')); r.type = 'button';
      const m = h('div', 'cm-rm'), l1 = h('div', 'cm-l'), l2 = h('div', 'cm-l');
      l1.append(h('span', 'cm-nm', nameOf(c.other)), h('span', 'cm-tm', c.time_label || ''));
      l2.append(h('span', 'cm-pv', c.preview ? (c.preview_is_mine ? 'You: ' : '') + c.preview : (c.is_request ? 'Message request' : '')));
      if (c.unread > 0) l2.append(h('span', 'cm-n', c.unread)); else if (c.is_request) l2.append(h('span', 'cm-chip', 'Request'));
      m.append(l1, l2); r.append(avatar(c.other, 52), m); r.onclick = () => openThread(c.other.username); return r;
    }));
  }
  $('cm-q').oninput = e => { q = e.target.value; renderRows(); };

  /* ---------- thread ---------- */
  async function openThread(handle) {
    active = handle; thread = null; search = {on: false, q: '', hits: 0, i: 0}; $('cm-sbar').hidden = true; clearPending();
    root.classList.add('open'); $('cm-blank').hidden = true; $('cm-view').hidden = false; note.textContent = '';
    msgsEl.replaceChildren(h('div', 'cm-empty', 'Loading…')); applyWp();
    history.replaceState(null, '', '/messages/@' + handle); renderRows();
    await loadThread(handle, true); if (matchMedia('(min-width:1024px)').matches) input.focus();
  }
  async function loadThread(handle, first) {
    try {
      const t = await api('/api/messages/threads/' + enc(handle)); if (active !== handle) return;
      thread = t; renderThread(first); if (infoOpen) renderInfo();
      if (t.unread > 0 && t.conversation) api(`/api/messages/${t.conversation.public_id}/read`, 'POST').then(loadInbox).catch(() => {});
    } catch (e) { if (active === handle) msgsEl.replaceChildren(h('div', 'cm-err', `Couldn't open this chat (${e.status || 'network'}): ${e.message}`)); }
  }
  function countHits(msgs, sq) { if (!sq) return 0; let n = 0; for (const m of msgs) { const low = (m.body || '').toLowerCase(); let i = 0, j; while ((j = low.indexOf(sq, i)) > -1) { n++; i = j + sq.length; } } return n; }
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
      const ph = photoOf(m), row = h('div', 'cm-m ' + (m.is_mine ? 'me' : 'th')), b = h('div', 'cm-b' + (tail ? ' tail' : '') + (ph ? ' img' : ''));
      if (ph) { const im = h('img', 'cm-img'); im.src = ph; im.alt = 'Photo'; im.loading = 'lazy'; im.onclick = () => lightbox(ph); b.append(im); }
      if (m.kind === 'shared_product' && m.shared_product_slug) { const a = h('a', 'cm-share'); a.href = '/product/' + enc(m.shared_product_slug); a.append(ico('sell'), h('span', '', 'Shared a product')); b.append(a); }
      if (m.kind === 'shared_profile') { const hd = m.shared_username || (m.shared_user && m.shared_user.username); if (hd) { const a = h('a', 'cm-share'); a.href = '/@' + hd; a.append(ico('person'), h('span', '', 'Shared @' + hd)); b.append(a); } }
      if (m.body) { const s = h('span', 'cm-t'); s.append(...hl(m.body)); b.append(s); }
      const ti = h('span', 'cm-time', tfmt(d)); ti.title = m.exact_time || ''; b.append(ti); row.append(b); nodes.push(row);
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
  function closeThread() { active = null; thread = null; infoOpen = false; info.hidden = true; root.classList.remove('open'); $('cm-view').hidden = true; $('cm-blank').hidden = false; history.replaceState(null, '', '/messages'); renderRows(); }
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
  $('cm-act').onclick = e => { if (!hasContent()) { e.preventDefault(); toast('Voice notes are coming in the next update'); } };
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
  const emo = $('cm-emoji'); EMOJI.forEach(x => { const b = h('button', '', x); b.type = 'button'; b.onclick = () => { const a = input.selectionStart ?? input.value.length, z = input.selectionEnd ?? a; input.setRangeText(x, a, z, 'end'); input.dispatchEvent(new Event('input')); input.focus(); }; emo.append(b); });
  $('cm-emo').onclick = e => { e.stopPropagation(); emo.hidden = !emo.hidden; };
  document.addEventListener('click', e => { if (!emo.contains(e.target)) emo.hidden = true; });
  $('cm-form').onsubmit = async ev => {
    ev.preventDefault(); const body = input.value.trim(); if ((!body && !pending) || !active || !thread || !thread.can_send) return;
    $('cm-act').disabled = true; note.textContent = '';
    try {
      if (pending) { const fd = new FormData(); fd.append('file', pending.file); if (body) fd.append('body', body); await api(`/api/messages/threads/${enc(active)}/photo`, 'POST', fd); }
      else await api('/api/messages/threads/' + enc(active), 'POST', {kind: 'text', body});
      input.value = ''; input.style.height = ''; clearPending(); await loadThread(active, true); loadInbox();
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
  function renderInfo() {
    const t = thread; if (!t) return; const u = t.other, nodes = [];
    const hd = h('div', 'cm-ihead'); hd.append(h('span', '', 'Contact info')); const x = h('button', 'cm-ib sm'); x.type = 'button'; x.setAttribute('aria-label', 'Close'); x.append(ico('close')); x.onclick = () => { infoOpen = false; info.hidden = true; }; hd.append(x); nodes.push(hd);
    const top = h('div', 'cm-top'); top.append(avatar(u, 88), h('div', '', nameOf(u)), h('div', 'cm-sub', '@' + u.username)); top.children[1].style.cssText = 'font-size:20px;font-weight:800;margin-bottom:2px'; nodes.push(top);
    const acts = h('div', 'cm-acts'); const a1 = h('button', 'cm-act'); a1.type = 'button'; const b1 = h('span', 'cm-ib'); b1.append(ico('search', '')); a1.append(b1, 'Search'); a1.onclick = () => { if (matchMedia('(max-width:1023px)').matches) { infoOpen = false; info.hidden = true; } openSearch(); };
    const a2 = h('a', 'cm-act'); a2.href = '/@' + u.username; const b2 = h('span', 'cm-ib'); b2.append(ico('person')); a2.append(b2, 'Profile'); acts.append(a1, a2); nodes.push(acts);
    const wp = h('button', 'cm-set'); wp.type = 'button'; const sw = h('span', 'cm-sw wp-' + wpFor(u.username)); wp.append(sw, h('span', 'sp', 'Chat wallpaper'), h('small', '', (WPS.find(w => w[0] === wpFor(u.username)) || WPS[0])[1]), ico('chevron_right')); wp.onclick = openWallpaper; nodes.push(wp);
    const imgs = (t.messages || []).map(photoOf).filter(Boolean);
    nodes.push(h('div', 'cm-h', `Media${imgs.length ? ' · ' + imgs.length : ''}`));
    if (imgs.length) { const g = h('div', 'cm-grid'); imgs.slice().reverse().forEach(s => { const i = h('img'); i.src = s; i.alt = 'Photo'; i.loading = 'lazy'; i.onclick = () => lightbox(s); g.append(i); }); nodes.push(g); } else nodes.push(h('div', 'cm-sub', 'Photos from this chat appear here.')), (nodes[nodes.length - 1].style.padding = '0 16px 14px');
    if (t.conversation) {
      const on = t.conversation.disappearing !== false, tr = h('button', 'cm-set'); tr.type = 'button'; tr.append(ico('timer'), h('span', 'sp', 'Disappearing messages'), h('span', 'cm-tog' + (on ? ' on' : ''))); tr.onclick = toggleTimer; nodes.push(tr);
      const ar = h('button', 'cm-set'); ar.type = 'button'; ar.append(ico('archive'), h('span', 'sp', 'Archive chat')); ar.onclick = async () => { try { await api(`/api/messages/${t.conversation.public_id}/archive`, 'POST'); closeThread(); loadInbox(); } catch (e) { toast(e.message); } }; nodes.push(ar);
    }
    const bl = h('button', 'cm-set red'); bl.type = 'button'; bl.append(ico('block'), h('span', 'sp', 'Block ' + nameOf(u))); bl.onclick = async () => { if (!confirm(`Block @${u.username}? You won't see each other's messages.`)) return; try { await api('/api/messages/blocks/' + enc(u.username), 'POST'); closeThread(); loadInbox(); } catch (e) { toast(e.message); } }; nodes.push(bl);
    const rp = h('button', 'cm-set red'); rp.type = 'button'; rp.append(ico('flag'), h('span', 'sp', 'Report')); rp.onclick = openReport; nodes.push(rp);
    info.replaceChildren(...nodes);
  }
  function openReport() {
    const u = thread.other; let pick = null;
    sheet('Report ' + nameOf(u), (s, close) => {
      const list = h('div'), noteEl = h('textarea'); noteEl.rows = 3; noteEl.placeholder = 'Add a note (optional)'; const err = h('div', 'cm-note');
      reasons.forEach(r => { const v = Array.isArray(r) ? r[0] : (r && typeof r === 'object' ? (r.value ?? r.key ?? r.id) : r), l = Array.isArray(r) ? r[1] : (r && typeof r === 'object' ? (r.label ?? r.name ?? v) : r); const b = h('button', 'cm-opt'); b.type = 'button'; b.append(ico('radio_button_unchecked'), h('span', '', String(l))); b.onclick = () => { pick = v; list.querySelectorAll('.cm-opt').forEach(x => { x.classList.remove('on'); x.firstChild.textContent = 'radio_button_unchecked'; }); b.classList.add('on'); b.firstChild.textContent = 'radio_button_checked'; }; list.append(b); });
      const go = h('button', 'cm-ib p', 'Send report'); go.type = 'button'; go.style.cssText = 'width:100%;border-radius:22px;font-weight:700'; go.onclick = async () => { if (!pick) { err.textContent = 'Choose a reason first.'; return; } try { await api('/api/messages/reports/' + enc(u.username), 'POST', {reason: pick, note: noteEl.value.trim() || null, conversation_public_id: thread.conversation ? thread.conversation.public_id : null}); close(); toast('Report sent. Thank you.'); } catch (e) { err.textContent = e.message; } };
      s.append(list, noteEl, err, go);
    });
  }
  function openWallpaper() {
    let key = wpFor(thread.other.username), scope = 'chat';
    sheet('Chat wallpaper', (s, close) => {
      const prev = h('div', 'cm-prev wp-' + key); const b1 = h('div', 'cm-b tail', 'Is the blue tote still available?'), b2 = h('div', 'cm-b tail', 'Yes it is, in stock.'); const r1 = h('div', 'cm-m th'), r2 = h('div', 'cm-m me'); r1.append(b1); r2.append(b2); prev.append(r1, r2);
      const seg = h('div', 'cm-seg'); [['chat', 'This chat'], ['all', 'All chats']].forEach(([k, l]) => { const b = h('button', k === scope ? 'on' : '', l); b.type = 'button'; b.onclick = () => { scope = k; seg.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); }; seg.append(b); });
      const grid = h('div', 'cm-sws'); WPS.forEach(([k, l]) => { const b = h('button', 'cm-swb' + (k === key ? ' on' : '')); b.type = 'button'; b.append(h('i', 'wp-' + k), l); b.onclick = () => { key = k; prev.className = 'cm-prev wp-' + k; grid.querySelectorAll('.cm-swb').forEach(x => x.classList.toggle('on', x === b)); }; grid.append(b); });
      const set = h('button', 'cm-ib p', 'Set wallpaper'); set.type = 'button'; set.style.cssText = 'width:100%;border-radius:22px;font-weight:700;margin-top:16px'; set.onclick = () => { setWp(key, scope); close(); if (infoOpen) renderInfo(); toast('Wallpaper set'); };
      const soon = h('div', 'cm-sub', 'Photo wallpapers with crop arrive in the next update.'); soon.style.marginTop = '12px'; soon.style.textAlign = 'center';
      s.append(prev, seg, grid, set, soon);
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
        box.replaceChildren(...(arr.length ? arr.map(c => { const u = c.other || c.user || c, b = h('button', 'cm-row'); b.type = 'button'; const m = h('div', 'cm-rm'); m.append(h('div', 'cm-nm', nameOf(u)), h('div', 'cm-sub', '@' + u.username)); b.append(avatar(u, 44), m); b.onclick = () => { close(); openThread(u.username); }; return b; }) : [h('div', 'cm-empty', 'Follow someone to message them, or type a username above.')]));
      } catch { box.replaceChildren(); }
    });
  }
  $('cm-new').onclick = openCompose; $('cm-new2').onclick = openCompose;
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { layer.replaceChildren(); emo.hidden = true; document.querySelectorAll('.cm-lb').forEach(x => x.remove()); } });

  /* ---------- live socket, polling fallback ---------- */
  let backoff = 1000, pingT = null, pollT = null, refT = null;
  const refresh = () => { clearTimeout(refT); refT = setTimeout(() => { loadInbox(); if (active) loadThread(active, false); }, 150); };
  function onFrame(f) {
    switch (f.type) {
      case 'ready': online = new Set(f.online || []); renderRows(); break;
      case 'presence': f.online ? online.add(f.username) : online.delete(f.username); if (thread) renderThread(false); renderRows(); break;
      case 'typing': if (thread && thread.conversation && f.conversation === thread.conversation.public_id) { typingUntil = f.state === 'stop' ? 0 : Date.now() + 4000; renderThread(false); setTimeout(() => thread && renderThread(false), 4100); } break;
      case 'pong': break;
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
  fit(); requestAnimationFrame(fit); setTimeout(fit, 300); syncAct(); loadInbox(); connect();
  const target = D.shareUser || D.open;
  if (target) openThread(target).then(() => { if (D.shareSlug && !input.value) { input.value = location.origin + '/product/' + D.shareSlug; syncAct(); } });
})();
