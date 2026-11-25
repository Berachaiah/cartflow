/* Stories: the rail's viewer.
 *
 * The rail used to be decoration — product photos mounted in a shop's ring, a
 * viewer with no author, and a like button that only animated. Everything this
 * file does maps to a real row now:
 *
 *   cfOpenStory(i)        opens group i (a person), slide 0
 *   cfNextStory/Prev      move one slide, then one person
 *   like / repost         POST /api/stories/{id}/like | /repost
 *   opening a slide       POST /api/stories/{id}/view  (drives the muted ring)
 *
 * The data comes from the server (`window.CF_STORIES`, built by
 * app/services/stories.py) so the rail and the viewer can never disagree about
 * who posted what, and a signed-out visitor can watch without a session — the
 * write controls simply say what is missing.
 *
 * Deliberately not a class or a framework: this is one overlay with four
 * buttons. Autoplay is a 6s timer plus a CSS width transition on the progress
 * bar; a requestAnimationFrame loop would buy sub-pixel smoothness nobody can
 * see on a 3px bar.
 */
(() => {
  'use strict';

  const overlay = document.getElementById('storyOverlay');
  if (!overlay) return;

  const groups = () => window.CF_STORIES || [];
  const signedIn = () => !!window.CF_VIEWER;
  const DURATION = 6000;

  let gi = 0;
  let si = 0;
  let timer = null;
  let paused = false;

  const $ = id => document.getElementById(id);
  const toast = msg => (typeof window.showToast === 'function' ? window.showToast(msg) : null);
  const group = () => groups()[gi] || null;
  const slide = () => {
    const g = group();
    return g ? g.stories[si] || null : null;
  };
  const escapeHtml = s =>
    String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ---------- render ---------- */

  function paintProgress() {
    const g = group();
    const row = $('storyProgressRow');
    if (!g || !row) return;
    row.innerHTML = g.stories
      .map((_, i) => {
        const done = i < si;
        return `<div class="h-[3px] flex-1 rounded-full bg-white/25 overflow-hidden">
            <div class="h-full bg-white" style="width:${done ? 100 : 0}%;transition:width ${i === si ? DURATION : 0}ms linear" data-seg="${i}"></div>
          </div>`;
      })
      .join('');
  }

  function paintAvatar(g) {
    const box = $('storyAvatar');
    if (!box) return;
    box.replaceChildren();
    if (g.avatar) {
      const img = document.createElement('img');
      img.src = g.avatar;
      img.alt = '';
      img.className = 'w-10 h-10 rounded-full object-cover';
      box.append(img);
    } else {
      // Same silhouette the server draws, so a story by an account with no photo
      // is not the one place in the app that still shows a letter.
      box.innerHTML = '<svg class="w-10 h-10 rounded-full overflow-hidden" aria-hidden="true" focusable="false"><use href="#cf-avatar"/></svg>';
    }
  }

  function paint() {
    const g = group();
    const s = slide();
    if (!g || !s) return;

    const img = $('storyImage');
    img.src = s.image;
    img.alt = s.caption || `Story by ${g.name}`;

    paintAvatar(g);
    $('storyName').textContent = g.name;
    $('storyName').href = g.href;
    $('storyMeta').textContent = [s.time, s.is_repost ? 'reposted' : null, s.views ? `${s.views} views` : null]
      .filter(Boolean)
      .join(' · ');

    $('storyCaption').textContent = s.caption || '';
    $('storyCaption').classList.toggle('hidden', !s.caption);

    // Product chip: the story holds a SLUG, and the link is the same page the
    // feed tag opens, so the price shown there is the price there.
    const chip = $('storyProduct');
    if (s.product) {
      chip.href = '/product/' + encodeURIComponent(s.product);
      chip.classList.remove('hidden');
      chip.classList.add('flex');
      chip.querySelector('span:last-child').textContent = s.product.replace(/-/g, ' ');
    } else {
      chip.classList.add('hidden');
      chip.classList.remove('flex');
    }

    const likeBtn = $('storyLike');
    likeBtn.classList.toggle('liked', !!s.liked);
    likeBtn.setAttribute('aria-pressed', s.liked ? 'true' : 'false');
    $('storyLikes').textContent = s.likes ? Number(s.likes).toLocaleString() : '';

    const repostBtn = $('storyRepost');
    repostBtn.classList.toggle('reposted', !!s.reposted);
    repostBtn.setAttribute('aria-pressed', s.reposted ? 'true' : 'false');

    const reply = $('storyReplyLink');
    reply.href = '/messages/@' + encodeURIComponent(g.username);
    reply.textContent = signedIn() ? 'Send message' : 'Log in to reply';

    paintProgress();
    requestAnimationFrame(() => {
      const seg = document.querySelector(`[data-seg="${si}"]`);
      if (seg) seg.style.width = '100%';
    });

    markViewed(s);
    restartTimer();
  }

  /* ---------- navigation ---------- */

  function restartTimer() {
    clearTimeout(timer);
    timer = null;
    if (paused) return;
    timer = setTimeout(cfNextStory, DURATION);
  }

  window.cfOpenStory = function (index) {
    if (!groups().length) return;
    gi = Math.max(0, Math.min(index, groups().length - 1));
    si = 0;
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    paint();
  };

  window.cfCloseStory = function () {
    clearTimeout(timer);
    timer = null;
    overlay.classList.remove('open');
    document.body.style.overflow = '';
    // The ring follows what the server just recorded: the CSS class is a local
    // echo of a view row, not the source of truth.
    const g = group();
    const btns = document.querySelectorAll('#storyRow [onclick^="cfOpenStory"]');
    if (g && btns[gi]) {
      const ring = btns[gi].querySelector('.story-ring');
      if (ring) {
        ring.classList.remove('story-live');
        ring.classList.add('is-seen');
      }
    }
  };

  window.cfNextStory = function () {
    const g = group();
    if (!g) return;
    if (si < g.stories.length - 1) {
      si += 1;
      paint();
    } else if (gi < groups().length - 1) {
      gi += 1;
      si = 0;
      paint();
    } else {
      cfCloseStory();
    }
  };

  window.cfPrevStory = function () {
    if (!groups().length) return;
    if (si > 0) {
      si -= 1;
      paint();
    } else if (gi > 0) {
      gi -= 1;
      si = Math.max(0, (group()?.stories.length || 1) - 1);
      paint();
    } else {
      paint(); // first slide of the first group: rewind rather than close
    }
  };

  /* ---------- writes ---------- */

  async function markViewed(s) {
    if (!signedIn() || !s || s.seen) return;
    s.seen = true;
    try {
      const r = await fetch(`/api/stories/${encodeURIComponent(s.id)}/view`, {
        method: 'POST',
        credentials: 'same-origin',
      });
      if (r.ok) {
        const d = await r.json();
        s.views = d.view_count;
      }
    } catch (e) {
      /* A view that failed to record is not worth a toast: the story still plays. */
    }
  }

  window.cfLikeStory = function (btn) {
    const s = slide();
    if (!s) return;
    if (!signedIn()) {
      toast('Log in to like a story');
      return;
    }
    const icon = btn.querySelector('.material-symbols-outlined');
    icon.classList.add('like-anim');
    setTimeout(() => icon.classList.remove('like-anim'), 500);
    // Optimistic, then corrected by the server — the same contract the feed's
    // like uses, because a double-tap must not queue behind a round trip.
    const was = !!s.liked;
    s.liked = !was;
    s.likes += s.liked ? 1 : -1;
    paint();
    fetch(`/api/stories/${encodeURIComponent(s.id)}/like`, {
      method: 'POST',
      credentials: 'same-origin',
    })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status))))
      .then(d => {
        s.liked = d.liked;
        s.likes = d.like_count;
        if ($('storyLike')) {
          $('storyLike').classList.toggle('liked', !!d.liked);
          $('storyLikes').textContent = d.like_count ? Number(d.like_count).toLocaleString() : '';
        }
      })
      .catch(() => {
        s.liked = was;
        s.likes += was ? 1 : -1;
        if ($('storyLike')) $('storyLike').classList.toggle('liked', was);
        toast('Could not save that like');
      });
  };

  window.cfRepostStory = function (btn) {
    const s = slide();
    if (!s) return;
    if (!signedIn()) {
      toast('Log in to repost a story');
      return;
    }
    const icon = btn.querySelector('.material-symbols-outlined');
    icon.classList.add('save-anim');
    setTimeout(() => icon.classList.remove('save-anim'), 500);
    fetch(`/api/stories/${encodeURIComponent(s.id)}/repost`, {
      method: 'POST',
      credentials: 'same-origin',
    })
      .then(async r => {
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || d.message || 'Could not repost');
        return d;
      })
      .then(d => {
        s.reposted = true;
        s.reposts = d.reposts;
        btn.classList.add('reposted');
        toast('Reposted to your story');
      })
      .catch(e => toast(e.message || 'Could not repost'));
  };

  /* ---------- composer ---------- */

  window.cfStoryCompose = function () {
    if (!signedIn()) {
      location.href = '/login?next=/';
      return;
    }
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      fd.append('caption', '');
      toast('Posting your story…');
      try {
        const r = await fetch('/api/stories', { method: 'POST', credentials: 'same-origin', body: fd });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.detail || d.message || 'Could not post that story');
        }
        toast('Story posted');
        setTimeout(() => location.reload(), 600);
      } catch (e) {
        toast(e.message || 'Could not post that story');
      }
    };
    input.click();
  };

  /* ---------- input ---------- */

  document.addEventListener('keydown', e => {
    if (!overlay.classList.contains('open')) return;
    if (e.key === 'Escape') cfCloseStory();
    if (e.key === 'ArrowRight') cfNextStory();
    if (e.key === 'ArrowLeft') cfPrevStory();
  });

  // Holding a finger down pauses the timer, the way every stories UI does, so a
  // long caption can be read without the slide advancing under it.
  overlay.addEventListener('pointerdown', e => {
    if (e.target.closest('button, a, input')) return;
    paused = true;
    clearTimeout(timer);
  });
  overlay.addEventListener('pointerup', () => {
    paused = false;
    restartTimer();
  });
  overlay.addEventListener('pointercancel', () => {
    paused = false;
    restartTimer();
  });

  window.__cfStoryDebug = () => ({ gi, si, groups: groups().length });
})();
