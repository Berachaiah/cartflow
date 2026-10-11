(() => {
  const root = document.querySelector('[data-mx]');
  if (!root) return;
  const D = root.dataset, $ = id => document.getElementById(id);
  const shell = $('mx-shell'), listEl = $('mx-rows'), msgsEl = $('mx-msgs'), input = $('mx-input'), note = $('mx-note'), threadEl = $('mx-thread'), viewEl = $('mx-view');
  const BORDER = 'border-[color-mix(in_srgb,currentColor_12%,transparent)]';
  let inbox = {items: [], unread_conversations: 0, pending_requests: 0}, tab = 'all', q = '';
  let active = null, thread = null, online = new Set(), typingUntil = 0, lastTypingSent = 0, ws = null;

  /* ---------- helpers ---------- */
  const h = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const icon = (name, cls = '') => h('span', 'material-symbols-outlined ' + cls, name);
  const nameOf = u => u.display_name || u.name || u.full_name || u.username || '';
  const errMsg = (d, t) => { if (!d) return (t || '').slice(0, 200); const x = d.detail || d.message || d.error; if (typeof x === 'string') return x; if (x && x.message) return x.message; return JSON.stringify(d).slice(0, 200); };
  async function api(path, method = 'GET', body) {
    const r = await fetch(path, {method, credentials: 'same-origin', headers: body ? {'Content-Type': 'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
    const t = await r.text(); let d = null; try { d = JSON.parse(t); } catch {}
    if (!r.ok) { const e = new Error(errMsg(d, t)); e.status = r.status; throw e; }
    return d;
  }
  function avatar(u, size = 'h-12 w-12 text-[17px]') {
    const wrap = h('div', `relative shrink-0 ${size}`);
    const url = u.avatar_url || u.profile_image_url || u.avatar;
    if (url) { const i = h('img', 'h-full w-full rounded-full object-cover'); i.src = url; i.alt = ''; wrap.append(i); }
    else wrap.append(h('div', 'flex h-full w-full items-center justify-center rounded-full bg-primary font-bold text-background', (nameOf(u)[0] || '?').toUpperCase()));
    if (online.has(u.username)) wrap.append(h('span', 'absolute bottom-0 right-0 h-3 w-3 rounded-full border-2 border-[var(--c-card,#fff)] bg-green-500'));
    return wrap;
  }

  /* ---------- fit to the full screen ---------- */
  function fit() {
    const lg = matchMedia('(min-width:1024px)').matches, p = root.parentElement, cs = getComputedStyle(p);
    root.style.margin = `-${cs.paddingTop} -${cs.paddingRight} -${cs.paddingBottom} -${cs.paddingLeft}`;
    root.style.maxWidth = 'none';
    window.scrollTo(0, 0);
    const top = root.getBoundingClientRect().top;
    let bottom = 0;
    if (!lg) for (const n of document.querySelectorAll('nav')) {
      const r = n.getBoundingClientRect();
      if (getComputedStyle(n).position === 'fixed' && r.top > innerHeight / 2 && r.height > 0) bottom = Math.max(bottom, innerHeight - r.top);
    }
    shell.style.height = Math.max(320, innerHeight - top - bottom) + 'px';
    document.body.style.overflow = lg ? 'hidden' : '';
  }
  addEventListener('resize', fit); addEventListener('orientationchange', fit);

  /* ---------- inbox ---------- */
  function skeleton() {
    listEl.replaceChildren(...Array.from({length: 7}, () => {
      const r = h('div', 'flex animate-pulse items-center gap-3 px-3 py-3');
      const a = h('div', 'h-12 w-12 rounded-full bg-[color-mix(in_srgb,currentColor_10%,transparent)]');
      const m = h('div', 'flex-1 space-y-2'); m.append(h('div', 'h-3 w-1/2 rounded bg-[color-mix(in_srgb,currentColor_10%,transparent)]'), h('div', 'h-3 w-3/4 rounded bg-[color-mix(in_srgb,currentColor_7%,transparent)]'));
      r.append(a, m); return r;
    }));
  }
  async function loadInbox() {
    try { inbox = await api('/api/messages'); renderTabs(); renderRows(); }
    catch (e) { listEl.replaceChildren(h('div', 'm-3 rounded-2xl bg-red-500/10 p-4 text-[13.5px] text-red-500', `Couldn't load conversations (${e.status || 'network'}): ${e.message}`)); }
  }
  function renderTabs() {
    const defs = [['all', 'All', 0], ['unread', 'Unread', inbox.unread_conversations], ['requests', 'Requests', inbox.pending_requests]];
    $('mx-tabs').replaceChildren(...defs.map(([k, label, n]) => {
      const b = h('button', 'flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition ' + (tab === k ? 'bg-primary text-background' : 'bg-[color-mix(in_srgb,currentColor_8%,transparent)] hover:bg-[color-mix(in_srgb,currentColor_12%,transparent)]'), label);
      b.type = 'button';
      if (n) b.append(h('span', 'rounded-full px-1.5 text-[11px] ' + (tab === k ? 'bg-black/20' : 'bg-primary text-background'), n));
      b.onclick = () => { tab = k; renderTabs(); renderRows(); };
      return b;
    }));
  }
  function renderRows() {
    const s = q.toLowerCase();
    const items = (inbox.items || []).filter(c =>
      (tab === 'all' || (tab === 'unread' && c.unread > 0) || (tab === 'requests' && c.is_request)) &&
      (!s || (nameOf(c.other) + ' ' + c.other.username + ' ' + (c.preview || '')).toLowerCase().includes(s)));
    if (!items.length) {
      const e = h('div', 'flex flex-col items-center px-6 py-14 text-center');
      e.append(icon(tab === 'requests' ? 'mark_email_unread' : 'chat_bubble', 'text-[40px] opacity-40'),
        h('p', 'mt-3 text-[14px] font-semibold', s ? 'No matches' : tab === 'all' ? 'No conversations yet' : 'Nothing here'),
        h('p', 'mt-1 text-[13px] opacity-60', tab === 'all' && !s ? 'Tap the pencil to start one.' : ''));
      listEl.replaceChildren(e); return;
    }
    listEl.replaceChildren(...items.map(c => {
      const on = c.other.username === active;
      const row = h('button', 'group flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-left transition ' + (on ? 'bg-[color-mix(in_srgb,currentColor_10%,transparent)]' : 'hover:bg-[color-mix(in_srgb,currentColor_6%,transparent)]'));
      row.type = 'button';
      const main = h('div', 'min-w-0 flex-1'), l1 = h('div', 'flex items-baseline justify-between gap-2'), l2 = h('div', 'mt-0.5 flex items-center justify-between gap-2');
      l1.append(h('span', 'truncate text-[15px] ' + (c.unread ? 'font-extrabold' : 'font-semibold'), nameOf(c.other)), h('span', 'shrink-0 text-[12px] ' + (c.unread ? 'font-bold text-primary' : 'opacity-55'), c.time_label || ''));
      l2.append(h('span', 'truncate text-[13.5px] ' + (c.unread ? 'font-semibold' : 'opacity-65'), c.preview ? (c.preview_is_mine ? 'You: ' : '') + c.preview : (c.is_request ? 'Message request' : '')));
      if (c.unread > 0) l2.append(h('span', 'flex h-5 min-w-[20px] shrink-0 items-center justify-center rounded-full bg-primary px-1.5 text-[11px] font-bold text-background', c.unread));
      main.append(l1, l2); row.append(avatar(c.other), main);
      row.onclick = () => openThread(c.other.username);
      return row;
    }));
  }
  $('mx-q').oninput = e => { q = e.target.value; renderRows(); };

  /* ---------- thread ---------- */
  const OPEN = ['max-lg:!flex', 'max-lg:fixed', 'max-lg:inset-0', 'max-lg:z-[60]', 'max-lg:bg-[var(--c-bg,#fff)]'];
  function showView(on) {
    threadEl.classList.toggle('lg:flex', true);
    OPEN.forEach(c => threadEl.classList.toggle(c, on));
    $('mx-blank').style.display = on ? 'none' : '';
    viewEl.hidden = !on; viewEl.style.display = on ? 'flex' : 'none'; viewEl.style.flexDirection = 'column';
  }
  async function openThread(handle) {
    active = handle; thread = null; showView(true); $('mx-menu').hidden = true;
    msgsEl.replaceChildren(h('div', 'py-10 text-center text-[13px] opacity-50', 'Loading…')); note.textContent = '';
    history.replaceState(null, '', '/messages/@' + handle);
    renderRows();
    await loadThread(handle, true);
    if (matchMedia('(min-width:1024px)').matches) input.focus();
  }
  async function loadThread(handle, first) {
    try {
      const t = await api('/api/messages/threads/' + encodeURIComponent(handle));
      if (active !== handle) return;
      thread = t; renderThread(first);
      if (t.unread > 0 && t.conversation) api(`/api/messages/${t.conversation.public_id}/read`, 'POST').then(loadInbox).catch(() => {});
    } catch (e) { if (active === handle) msgsEl.replaceChildren(h('div', 'm-3 rounded-2xl bg-red-500/10 p-4 text-[13.5px] text-red-500', `Couldn't open this chat (${e.status || 'network'}): ${e.message}`)); }
  }
  const dayLabel = d => {
    const t = new Date(), y = new Date(Date.now() - 864e5);
    if (d.toDateString() === t.toDateString()) return 'Today';
    if (d.toDateString() === y.toDateString()) return 'Yesterday';
    return d.toLocaleDateString(undefined, {weekday: 'short', day: 'numeric', month: 'short', year: d.getFullYear() === t.getFullYear() ? undefined : 'numeric'});
  };
  function renderThread(first) {
    const t = thread, u = t.other, typing = Date.now() < typingUntil;
    $('mx-hav').replaceChildren(avatar(u, 'h-10 w-10 text-[15px]'));
    $('mx-hname').textContent = nameOf(u);
    const hs = $('mx-hsub'); hs.textContent = typing ? 'typing…' : (online.has(u.username) || t.is_active_now) ? 'Active now' : (t.last_seen_label || '@' + u.username);
    hs.className = 'truncate text-[12.5px] ' + (typing || online.has(u.username) || t.is_active_now ? 'font-semibold text-green-500' : 'opacity-60');
    $('mx-profile').href = '/@' + u.username;
    $('mx-banner').hidden = !(t.is_incoming_request && t.conversation);

    const read = t.their_last_read_at ? new Date(t.their_last_read_at).getTime() : 0;
    const nodes = []; let prev = null, prevDay = '';
    const msgs = t.messages || [];
    msgs.forEach((m, i) => {
      const d = new Date(m.sent_at), dk = d.toDateString();
      if (dk !== prevDay) { const sep = h('div', 'my-4 flex justify-center'); sep.append(h('span', 'rounded-full px-3 py-1 text-[11.5px] font-semibold bg-[color-mix(in_srgb,currentColor_8%,transparent)] opacity-80', dayLabel(d))); nodes.push(sep); prev = null; prevDay = dk; }
      const next = msgs[i + 1], lastOfGroup = !next || next.is_mine !== m.is_mine || new Date(next.sent_at).toDateString() !== dk;
      const firstOfGroup = !prev || prev.is_mine !== m.is_mine;
      const row = h('div', 'flex ' + (m.is_mine ? 'justify-end ' : 'justify-start ') + (firstOfGroup ? 'mt-3' : 'mt-0.5'));
      const bub = h('div', 'max-w-[78%] whitespace-pre-wrap break-words px-3.5 py-2 text-[15px] leading-snug shadow-sm lg:max-w-[65%] ' +
        (m.is_mine ? 'bg-primary text-background rounded-3xl ' + (lastOfGroup ? 'rounded-br-md' : '') : 'bg-[color-mix(in_srgb,currentColor_9%,transparent)] rounded-3xl ' + (lastOfGroup ? 'rounded-bl-md' : '')),
        m.body || (m.kind && m.kind !== 'text' ? '[' + m.kind + ']' : ''));
      bub.title = m.exact_time || '';
      row.append(bub); nodes.push(row);
      if (lastOfGroup) {
        const meta = h('div', 'mt-1 flex items-center gap-1 text-[11px] opacity-60 ' + (m.is_mine ? 'justify-end' : 'justify-start'), m.time_label || '');
        if (m.is_mine) { const seen = read && d.getTime() <= read; const tick = icon(seen ? 'done_all' : 'done', 'text-[14px] ' + (seen ? 'text-primary' : '')); meta.append(tick); meta.classList.remove('opacity-60'); meta.firstChild && (meta.style.opacity = '.85'); }
        nodes.push(meta);
      }
      prev = m;
    });
    if (!msgs.length) { const e = h('div', 'flex h-full flex-col items-center justify-center text-center'); e.append(h('div', 'text-[42px]', '👋'), h('p', 'mt-2 text-[15px] font-semibold', 'Say hello to ' + nameOf(u)), h('p', 'mt-1 text-[13px] opacity-60', 'Messages here are one to one.')); nodes.push(e); }
    if (typing) { const r = h('div', 'mt-2 flex'); const b = h('div', 'flex gap-1 rounded-3xl rounded-bl-md px-4 py-3 bg-[color-mix(in_srgb,currentColor_9%,transparent)]'); for (const d of ['0ms', '150ms', '300ms']) { const s = h('span', 'h-2 w-2 animate-bounce rounded-full bg-current opacity-50'); s.style.animationDelay = d; b.append(s); } r.append(b); nodes.push(r); }

    const near = first || msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 120;
    msgsEl.replaceChildren(...nodes);
    if (near) msgsEl.scrollTop = msgsEl.scrollHeight;
    input.disabled = $('mx-send').disabled = !t.can_send;
    note.className = 'px-4 pb-1 text-[12.5px] empty:hidden ' + (t.can_send ? '' : 'text-red-500');
    note.textContent = t.can_send ? '' : (t.blocked_reason || "You can't send messages in this conversation.");
  }
  msgsEl.addEventListener('scroll', () => { $('mx-down').hidden = msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 200; });
  $('mx-down').onclick = () => msgsEl.scrollTo({top: msgsEl.scrollHeight, behavior: 'smooth'});

  $('mx-form').onsubmit = async ev => {
    ev.preventDefault();
    const body = input.value.trim(); if (!body || !active) return;
    $('mx-send').disabled = true; note.textContent = '';
    try {
      await api('/api/messages/threads/' + encodeURIComponent(active), 'POST', {body});
      input.value = ''; input.style.height = '';
      await loadThread(active, true); loadInbox();
    } catch (e) { note.className = 'px-4 pb-1 text-[12.5px] text-red-500'; note.textContent = e.message; }
    $('mx-send').disabled = !(thread && thread.can_send); input.focus();
  };
  input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && matchMedia('(min-width:1024px)').matches) { e.preventDefault(); $('mx-form').requestSubmit(); } });
  input.addEventListener('input', () => {
    input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 128) + 'px';
    const now = Date.now();
    if (ws && ws.readyState === 1 && thread && thread.conversation && now - lastTypingSent > 3000) { lastTypingSent = now; ws.send(JSON.stringify({type: 'typing', conversation: thread.conversation.public_id, state: 'start'})); }
  });
  async function act(path) { try { await api(path, 'POST'); await loadThread(active, false); loadInbox(); } catch (e) { note.className = 'px-4 pb-1 text-[12.5px] text-red-500'; note.textContent = e.message; } }
  $('mx-accept').onclick = () => act(`/api/messages/${thread.conversation.public_id}/accept`);
  $('mx-decline').onclick = async () => { await act(`/api/messages/${thread.conversation.public_id}/decline`); closeThread(); };
  function closeThread() { active = null; thread = null; showView(false); history.replaceState(null, '', '/messages'); renderRows(); }
  $('mx-back').onclick = closeThread;
  $('mx-more').onclick = e => { e.stopPropagation(); $('mx-menu').hidden = !$('mx-menu').hidden; };
  document.addEventListener('click', () => { $('mx-menu').hidden = true; });
  $('mx-block').onclick = async () => {
    if (!active || !confirm(`Block @${active}? You won't see each other's messages.`)) return;
    try { await api('/api/messages/blocks/' + encodeURIComponent(active), 'POST'); closeThread(); loadInbox(); } catch (e) { alert(e.message); }
  };
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { $('mx-over').hidden = true; $('mx-menu').hidden = true; } });

  /* ---------- new message ---------- */
  const over = $('mx-over');
  async function openCompose() {
    over.hidden = false; $('mx-handle').value = ''; $('mx-handle').focus();
    const box = $('mx-cands'); box.replaceChildren(h('div', 'py-6 text-center text-[13px] opacity-50', 'Loading people you follow…'));
    try {
      const d = await api('/api/messages/candidates');
      const arr = Array.isArray(d) ? d : (d.items || d.candidates || d.users || []);
      box.replaceChildren(...(arr.length ? arr.map(c => {
        const u = c.other || c.user || c, row = h('button', 'flex w-full items-center gap-3 rounded-2xl px-2 py-2 text-left hover:bg-[color-mix(in_srgb,currentColor_8%,transparent)]'), m = h('div', 'min-w-0');
        row.type = 'button'; m.append(h('div', 'truncate text-[15px] font-semibold', nameOf(u)), h('div', 'text-[12.5px] opacity-60', '@' + u.username));
        row.append(avatar(u, 'h-11 w-11 text-[16px]'), m); row.onclick = () => { over.hidden = true; openThread(u.username); };
        return row;
      }) : [h('div', 'py-6 text-center text-[13px] opacity-60', 'Follow someone to message them, or type a username above.')]));
    } catch { box.replaceChildren(); }
  }
  $('mx-new').onclick = openCompose; $('mx-new2').onclick = openCompose;
  $('mx-close').onclick = () => over.hidden = true;
  over.addEventListener('click', e => { if (e.target === over) over.hidden = true; });
  $('mx-goform').onsubmit = ev => { ev.preventDefault(); const v = $('mx-handle').value.trim().replace(/^@/, ''); if (v) { over.hidden = true; openThread(v); } };

  /* ---------- live socket with polling fallback ---------- */
  let backoff = 1000, pingT = null, pollT = null, refreshT = null;
  const refresh = () => { clearTimeout(refreshT); refreshT = setTimeout(() => { loadInbox(); if (active) loadThread(active, false); }, 150); };
  function onFrame(f) {
    switch (f.type) {
      case 'ready': online = new Set(f.online || []); renderRows(); break;
      case 'presence': f.online ? online.add(f.username) : online.delete(f.username); if (thread) renderThread(false); renderRows(); break;
      case 'typing':
        if (thread && thread.conversation && f.conversation === thread.conversation.public_id) { typingUntil = f.state === 'stop' ? 0 : Date.now() + 4000; renderThread(false); setTimeout(() => thread && renderThread(false), 4100); }
        break;
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
  fit(); skeleton(); renderTabs(); showView(false);
  requestAnimationFrame(fit); setTimeout(fit, 300);
  loadInbox(); connect();
  const target = D.shareUser || D.open;
  if (target) openThread(target).then(() => { if (D.shareSlug && !input.value) input.value = location.origin + '/product/' + D.shareSlug; });
})();
