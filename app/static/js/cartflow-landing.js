/*
  Landing page behaviour: reveal-on-scroll and the sticky nav's surface change.

  Both are deliberately cheap. The reveal is one IntersectionObserver that
  unobserves each element as soon as it has fired — no scroll listener, no
  getBoundingClientRect per frame, nothing to keep running after the page has
  been read. The nav check is a single IntersectionObserver on a marker element
  at the top of the page rather than a scroll handler, for the same reason.

  If this file never loads, the page is still fully readable: `.lp-js` is what
  makes `.lp-reveal` start transparent, and that class is added here. Nothing is
  hidden by CSS alone.
*/
(function () {
  var root = document.documentElement;
  root.classList.add('lp-js');

  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---- reveal ---------------------------------------------------------- */
  var items = document.querySelectorAll('.lp-reveal');
  if (!reduced && 'IntersectionObserver' in window) {
    var reveal = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        reveal.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.12 });

    items.forEach(function (el) { reveal.observe(el); });
  } else {
    // Reduced motion, or an old browser: show everything immediately.
    items.forEach(function (el) { el.classList.add('is-visible'); });
  }

  /* ---- sticky nav ------------------------------------------------------ */
  var nav = document.getElementById('lpNav');
  if (nav) {
    if ('IntersectionObserver' in window) {
      var marker = document.createElement('div');
      marker.setAttribute('aria-hidden', 'true');
      marker.style.cssText = 'position:absolute;top:0;left:0;height:8px;width:1px;';
      document.body.appendChild(marker);
      var stuck = new IntersectionObserver(function (entries) {
        nav.classList.toggle('is-stuck', !entries[0].isIntersecting);
      }, { threshold: 0 });
      stuck.observe(marker);
    } else {
      nav.classList.add('is-stuck');
    }
  }
})();
