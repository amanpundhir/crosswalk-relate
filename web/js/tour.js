/* Crosswalk guided tour. Classic script, no dependencies. Never throws; does nothing if window.CW is missing.
 * Public: window.CWTour = { start(), startTab(tab), isActive(), reset() }
 * Storage: cw-tour-done ("1"), cw-tour-tabs (JSON {tab:1}), cw-tour-whatif ("1"). */
(function () {
  'use strict';
  var KEY_DONE = 'cw-tour-done', KEY_TABS = 'cw-tour-tabs', KEY_WI = 'cw-tour-whatif';
  var mem = {};
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { if (v === undefined) return mem[k] || null; mem[k] = v; } return null; }
  function wipe() { try { localStorage.removeItem(KEY_DONE); localStorage.removeItem(KEY_TABS); localStorage.removeItem(KEY_WI); } catch (e) { /* ignore */ } mem = {}; }
  function tabsSeen() { try { return JSON.parse(store(KEY_TABS) || '{}') || {}; } catch (e) { return {}; } }

  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  function phone() { return !!(window.matchMedia && matchMedia('(max-width: 640px)').matches); }
  function $(s, root) { try { return (root || document).querySelector(s); } catch (e) { return null; } }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function CW() { return window.CW && typeof window.CW.showTab === 'function' ? window.CW : null; }
  function stickyH() { var v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--sticky-h')); return isFinite(v) ? v : 60; }
  function visible(n) {
    if (!n || !n.getClientRects().length) return false;
    var r = n.getBoundingClientRect();
    return r.width >= 14 && r.height >= 14;
  }
  function find(sels) {
    var list = Array.isArray(sels) ? sels : [sels];
    for (var i = 0; i < list.length; i++) { var n = $(list[i]); if (n && visible(n)) return n; }
    return null;
  }

  // ---------------------------------------------------------------- steps
  var MAIN = [
    { sel: ['#verdict', '.intro h1'], title: 'The answer, in one line', text: 'This sentence says whether Harbor & Pine is ready for its audit, using the demo date as "today".' },
    { sel: ['#hero-kpis'], title: 'The key numbers', text: 'Covered, inherited and gap counts for the requirements an audit asks about. They update when you try a what-if.' },
    { sel: ['#panel-coverage .fam', '#panel-coverage .card', '#panel-coverage'], tab: 'coverage', title: 'Coverage and receipts', text: 'Open a family, then a requirement, to see its receipt: the chain from requirement to control to evidence.', place: 'top' },
    { sel: ['#panel-blast .stats', '#panel-blast .card', '#panel-blast'], tab: 'blast', title: 'What breaks', text: 'Pick a time window to see which evidence runs out and which requirements lose their coverage.' },
    { sel: ['.whatif', '#btn-expire', '#whatif-viz-root', '#start .start-list'], title: 'Try a what-if', text: 'Pretend evidence expires or a person leaves. The numbers update, and nothing is saved. Reset puts it all back.', place: 'bottom' },
    { sel: ['#panel-agent .card', '#panel-agent'], tab: 'agent', title: 'A wrong answer, caught', text: 'An AI agent gave an answer from an old spreadsheet. Crosswalk re-checked each claim against its receipt and corrected it.' },
    { sel: ['#panel-scorecard .card', '#panel-scorecard'], tab: 'scorecard', title: 'The scorecard', text: 'The same test questions answered with a spreadsheet and with Crosswalk, so you can compare how often each was right.' },
    { sel: ['#panel-graph .graph-head', '#graph-search', '#cy'], tab: 'graph', title: 'The graph', text: 'Search for any requirement, control, evidence or person, then click a circle to see what it connects to.' },
    { sel: ['#tour-start'], title: 'Take the tour again any time', text: 'This button replays the tour. Each tab also offers a short tour the first time you open it.', place: 'bottom' }
  ];
  var MINI = {
    coverage: [
      { sel: ['#panel-coverage .controls', '#panel-coverage .card'], title: 'Choose what to check', text: 'Pick a framework or an audit. Tick "Show gaps only" to see just what is missing.' },
      { sel: ['#panel-coverage .stats', '#panel-coverage .bar'], title: 'The counts', text: 'Covered is met directly with valid evidence. Inherited is met through a matching requirement in another framework. A gap is neither.' },
      { sel: ['#panel-coverage .fam', '#panel-coverage .fam-head'], title: 'Open a requirement', text: 'Open a family, then pick a requirement to see its receipt.', place: 'top' }
    ],
    blast: [
      { sel: ['#panel-blast .controls', '#panel-blast .card'], title: 'Look ahead', text: 'Choose how far ahead to look. Evidence that expires in that window is counted.' },
      { sel: ['#panel-blast .stats'], title: 'What would break', text: 'These counts show requirements that lose direct coverage in each framework.' },
      { sel: ['#panel-blast .grid2', '#panel-blast .card:last-child'], title: 'Evidence and owners', text: 'See which evidence is about to expire and which people own the controls at risk.', place: 'top' }
    ],
    adopt: [
      { sel: ['#panel-adopt .controls', '#panel-adopt .card'], title: 'Pick a framework', text: 'Inherited means a requirement is already met through a matching one in another framework.' },
      { sel: ['#adopt-rows', '#panel-adopt .card:nth-of-type(2)'], title: 'Reuse, do not redo', text: 'Each row is a requirement you can answer with evidence you already have.', place: 'top' }
    ],
    agent: [
      { sel: ['#panel-agent .quote', '#panel-agent .card'], title: 'What the agent said', text: 'A recorded answer from an AI agent that read the old spreadsheet.' },
      { sel: ['#panel-agent .claim', '#panel-agent .card'], title: 'Each claim, re-checked', text: 'Crosswalk replays the receipt behind each claim and flags any that fail.', place: 'top' },
      { sel: ['#panel-agent .fixed', '#panel-agent .card:last-child'], title: 'The corrected answer', text: 'Failed claims are dropped or fixed. Agents only propose changes; a person decides.', place: 'top' }
    ],
    scorecard: [
      { sel: ['#panel-scorecard .card.accent', '#panel-scorecard .card'], title: 'The headline', text: 'How often an agent was right with a spreadsheet, and how often with Crosswalk.' },
      { sel: ['#panel-scorecard .card:nth-of-type(2)', '#panel-scorecard .card:last-child', '#panel-scorecard'], title: 'The details', text: 'Below the headline you can see each measure and how it was tested.', place: 'top' }
    ],
    graph: [
      { sel: ['#graph-search', '#panel-graph .graph-head'], title: 'Search', text: 'Type an ID or name, such as a requirement, a control or a person.' },
      { sel: ['#cy'], title: 'The map', text: 'Each circle is one thing. Lines show how they connect. Click a circle to see its links.', place: 'right' },
      { sel: ['#graph-info', '#graph-legend'], title: 'Details and key', text: 'Details for the circle you pick appear here. The key explains the colours.', place: 'left' }
    ]
  };
  var TAB_NAMES = { coverage: 'Coverage', blast: 'What breaks', adopt: 'Inherited', agent: 'Agent log', scorecard: 'Scorecard', graph: 'Graph' };

  // ---------------------------------------------------------------- state
  var T = null; // active tour
  var hintEl = null, hintState = null;
  var mainDone = store(KEY_DONE) === '1';
  var ready = false, suppress = false, raf = 0, startTimer = 0;

  function reposition() {
    raf = 0;
    try { if (T && T.target) { placeRing(); placePop(); } if (hintState) placeHint(); } catch (e) { /* ignore */ }
  }
  function schedule() { if (!raf) raf = requestAnimationFrame(reposition); }

  // ---------------------------------------------------------------- tour engine
  function begin(steps, opts) {
    try {
      if (!CW() || !steps || !steps.length) return;
      if (T) finish('skip', true);
      closeHint();
      T = { steps: steps, i: -1, opts: opts || {}, token: 0, target: null, opener: document.activeElement, tab0: CW().S && CW().S.tab };
      T.shield = el('div', 'tour-shield');
      T.ring = el('div', 'tour-ring');
      T.pop = el('div', 'tour-pop'); T.pop.setAttribute('role', 'dialog'); T.pop.setAttribute('aria-modal', 'false'); T.pop.setAttribute('aria-labelledby', 'tour-title'); T.pop.setAttribute('aria-describedby', 'tour-text');
      T.title = el('h2', 'tour-title'); T.title.id = 'tour-title';
      T.text = el('p', 'tour-text'); T.text.id = 'tour-text';
      T.x = el('button', 'tour-x', '×'); T.x.type = 'button'; T.x.setAttribute('aria-label', 'Close tour');
      var foot = el('div', 'tour-foot');
      T.count = el('span', 'tour-count'); T.count.setAttribute('aria-live', 'polite');
      T.skip = el('button', 'tour-link', 'Skip tour'); T.skip.type = 'button';
      T.back = el('button', 'tour-btn', 'Back'); T.back.type = 'button';
      T.next = el('button', 'tour-btn tour-primary', 'Next'); T.next.type = 'button';
      foot.appendChild(T.count); foot.appendChild(T.skip); foot.appendChild(T.back); foot.appendChild(T.next);
      T.pop.appendChild(T.x); T.pop.appendChild(T.title); T.pop.appendChild(T.text); T.pop.appendChild(foot);
      T.x.onclick = T.skip.onclick = function () { finish('skip'); };
      T.back.onclick = function () { go(T.i - 1, -1); };
      T.next.onclick = function () { go(T.i + 1, 1); };
      T.pop.hidden = true;
      document.body.appendChild(T.shield); document.body.appendChild(T.ring); document.body.appendChild(T.pop);
      document.body.classList.add('tour-open');
      document.addEventListener('keydown', onKey, true);
      window.addEventListener('resize', schedule); window.addEventListener('scroll', schedule, true);
      go(0, 1);
    } catch (e) { try { finish('skip', true); } catch (e2) { /* ignore */ } }
  }

  function go(i, dir) {
    if (!T) return;
    if (i >= T.steps.length) { finish('finish'); return; }
    if (i < 0) i = 0;
    var tok = ++T.token, step = T.steps[i];
    try {
      var cw = CW();
      if (step.tab && cw && cw.S && cw.S.tab !== step.tab) { suppress = true; try { cw.showTab(step.tab, { push: false }); } finally { suppress = false; } }
      if (step.before) step.before();
    } catch (e) { /* carry on; the target check decides */ }
    var tries = 0;
    (function poll() {
      if (!T || tok !== T.token) return;
      var n = find(step.sel);
      if (n) { T.i = i; show(step, n); return; }
      if (++tries < 20) { setTimeout(poll, 60); return; }
      // target missing: skip gracefully in the direction of travel
      var j = i + dir;
      if (j >= T.steps.length) { finish('finish'); return; }
      if (j < 0) { if (T.i < 0) go(i + 1, 1); return; }
      go(j, dir);
    })();
  }

  function show(step, node) {
    T.target = node;
    T.title.textContent = step.title; T.text.textContent = step.text;
    T.count.textContent = (T.i + 1) + ' of ' + T.steps.length;
    var last = T.i === T.steps.length - 1;
    T.next.textContent = last ? 'Finish' : 'Next';
    T.back.hidden = T.i === 0;
    T.skip.hidden = last;
    T.place = step.place;
    T.pop.hidden = false;
    scrollTo(node);
    placeRing(); placePop();
    if (!T.animated) requestAnimationFrame(function () { if (T && T.ring) { T.ring.classList.add('tour-anim'); T.animated = true; } });
    try { T.next.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
  }

  function region() {
    var top = stickyH() + 10, bottom = window.innerHeight - 10;
    if (T && T.pop && phone() && !T.pop.hidden) bottom = window.innerHeight - T.pop.offsetHeight - 10;
    return { top: top, bottom: Math.max(bottom, top + 60) };
  }
  function scrollTo(node) {
    var r = node.getBoundingClientRect(), reg = region();
    var anc = node.closest && node.closest('.top, .tabs-bar, #whatif-dock');
    if (anc) { var pos = getComputedStyle(anc).position; if ((pos === 'sticky' || pos === 'fixed') && r.top >= 0 && r.bottom <= window.innerHeight) return; }
    if (r.top >= reg.top - 2 && r.bottom <= reg.bottom + 2) return;
    if (r.height > reg.bottom - reg.top && r.top >= reg.top - 2 && r.top < reg.bottom - 40) return;
    window.scrollBy({ top: r.top - reg.top - 6, left: 0, behavior: 'instant' });
  }
  function placeRing() {
    if (!T.target || !document.contains(T.target)) return;
    var r = T.target.getBoundingClientRect(), pad = 6, vw = window.innerWidth, vh = window.innerHeight;
    var top = Math.max(r.top - pad, 2), left = Math.max(r.left - pad, 2);
    var bottom = Math.min(r.bottom + pad, vh - 2), right = Math.min(r.right + pad, vw - 2);
    var s = T.ring.style;
    s.top = top + 'px'; s.left = left + 'px'; s.width = Math.max(right - left, 8) + 'px'; s.height = Math.max(bottom - top, 8) + 'px';
    T.rect = { top: top, left: left, right: right, bottom: bottom };
  }
  function layout(pop, rect, prefer) {
    var s = pop.style;
    if (phone()) { s.left = s.top = s.right = s.bottom = ''; return; }
    var w = pop.offsetWidth, h = pop.offsetHeight, vw = window.innerWidth, vh = window.innerHeight, gap = 12, m = 8;
    var minTop = Math.min(stickyH() + 6, vh / 3);
    var order = ['bottom', 'top', 'right', 'left']; if (prefer) order = [prefer].concat(order.filter(function (o) { return o !== prefer; }));
    var cx = (rect.left + rect.right) / 2, cy = (rect.top + rect.bottom) / 2, x, y, ok = false;
    function clampX(v) { return Math.min(Math.max(v, m), vw - w - m); }
    for (var i = 0; i < order.length && !ok; i++) {
      var o = order[i];
      if (o === 'bottom') { x = clampX(cx - w / 2); y = rect.bottom + gap; ok = y + h <= vh - m; }
      else if (o === 'top') { x = clampX(cx - w / 2); y = rect.top - gap - h; ok = y >= minTop; }
      else if (o === 'right') { x = rect.right + gap; y = Math.min(Math.max(cy - h / 2, minTop), vh - h - m); ok = x + w <= vw - m; }
      else { x = rect.left - gap - w; y = Math.min(Math.max(cy - h / 2, minTop), vh - h - m); ok = x >= m; }
    }
    if (!ok) { x = clampX(cx - w / 2); y = Math.max(minTop, vh - h - 16); } // target fills the screen: float over its lower part
    s.right = s.bottom = 'auto'; s.left = Math.round(x) + 'px'; s.top = Math.round(y) + 'px';
  }
  function placePop() { if (T && T.rect && !T.pop.hidden) layout(T.pop, T.rect, T.place); }

  function onKey(e) {
    if (!T) return;
    var k = e.key, a = document.activeElement, inBtn = a && a.tagName === 'BUTTON' && T.pop.contains(a);
    if (k === 'Escape') { e.preventDefault(); e.stopPropagation(); finish('skip'); }
    else if (k === 'ArrowRight' || (k === 'Enter' && !inBtn)) { e.preventDefault(); T.next.click(); }
    else if (k === 'ArrowLeft') { e.preventDefault(); if (!T.back.hidden) T.back.click(); }
    else if (k === 'Tab') {
      var f = [T.x, T.skip, T.back, T.next].filter(function (b) { return !b.hidden; });
      var idx = f.indexOf(a);
      if (idx < 0) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (e.shiftKey && idx === 0) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && idx === f.length - 1) { e.preventDefault(); f[0].focus(); }
    }
  }

  function finish(kind, quiet) {
    var t = T; if (!t) return;
    T = null; t.token = -1;
    document.removeEventListener('keydown', onKey, true);
    window.removeEventListener('resize', schedule); window.removeEventListener('scroll', schedule, true);
    [t.shield, t.ring, t.pop].forEach(function (n) { if (n && n.parentNode) n.parentNode.removeChild(n); });
    document.body.classList.remove('tour-open');
    if (quiet) return;
    try {
      if (t.opts.main) { store(KEY_DONE, '1'); mainDone = true; }
      var cw = CW();
      if (t.opts.restore !== false && cw && cw.S && t.tab0 && cw.S.tab !== t.tab0) { suppress = true; try { cw.showTab(t.tab0, { push: false }); } finally { suppress = false; } }
      if (t.opener && document.contains(t.opener) && t.opener.focus) t.opener.focus({ preventScroll: true });
      if (t.opts.onEnd) t.opts.onEnd(kind);
    } catch (e) { /* ignore */ }
  }

  // ---------------------------------------------------------------- hint bubble (non-blocking)
  function closeHint() {
    if (hintEl && hintEl.parentNode) hintEl.parentNode.removeChild(hintEl);
    if (hintState && hintState.ring && hintState.ring.parentNode) hintState.ring.parentNode.removeChild(hintState.ring);
    hintEl = null; hintState = null;
  }
  function showHint(o) {
    try {
      if (T) return;
      closeHint();
      var b = el('div', 'tour-hint'); b.setAttribute('role', 'region'); b.setAttribute('aria-label', 'Tip');
      var x = el('button', 'tour-x', '×'); x.type = 'button'; x.setAttribute('aria-label', 'Dismiss tip');
      var h = el('p', 'tour-title', o.title); var p = el('p', 'tour-text', o.text);
      var foot = el('div', 'tour-foot');
      var primary = el('button', 'tour-btn tour-primary', o.primary); primary.type = 'button';
      foot.appendChild(primary);
      var second = null;
      if (o.secondary) { second = el('button', 'tour-link', o.secondary); second.type = 'button'; foot.appendChild(second); }
      b.appendChild(x); b.appendChild(h); b.appendChild(p); b.appendChild(foot);
      function done(act) { closeHint(); if (act && o.onPrimary) o.onPrimary(); else if (!act && o.onDismiss) o.onDismiss(); }
      primary.onclick = function () { done(true); };
      if (second) second.onclick = function () { done(false); };
      x.onclick = function () { done(false); };
      b.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.stopPropagation(); done(false); } });
      document.body.appendChild(b);
      hintEl = b; hintState = { anchor: o.anchor || null };
      if (o.anchor) { hintState.ring = el('div', 'tour-ring tour-soft'); document.body.appendChild(hintState.ring); }
      placeHint();
      window.addEventListener('resize', schedule); window.addEventListener('scroll', schedule, true);
    } catch (e) { closeHint(); }
  }
  function placeHint() {
    if (!hintEl) return;
    var n = hintState.anchor && find(hintState.anchor), vh = window.innerHeight;
    var r = n && n.getBoundingClientRect();
    var onScreen = r && r.bottom > stickyH() && r.top < vh - 40;
    if (hintState.ring) hintState.ring.style.display = onScreen && !phone() ? '' : 'none';
    if (onScreen && !phone()) {
      var rect = { top: Math.max(r.top, 2), left: Math.max(r.left, 2), right: Math.min(r.right, window.innerWidth - 2), bottom: Math.min(r.bottom, vh - 2) };
      var s = hintState.ring.style; s.top = rect.top - 4 + 'px'; s.left = rect.left - 4 + 'px'; s.width = rect.right - rect.left + 8 + 'px'; s.height = rect.bottom - rect.top + 8 + 'px';
      hintEl.classList.remove('tour-corner'); layout(hintEl, rect, 'bottom');
    } else {
      hintEl.classList.add('tour-corner');
      hintEl.style.left = hintEl.style.top = ''; hintEl.style.right = hintEl.style.bottom = '';
    }
  }

  // ---------------------------------------------------------------- triggers
  function startMain() { begin(MAIN, { main: true }); }
  function startTab(tab) { if (MINI[tab]) begin(MINI[tab], { restore: false }); }

  function offerTab(tab) {
    try {
      if (!MINI[tab] || T || !mainDone) return;
      var seen = tabsSeen(); if (seen[tab]) return;
      seen[tab] = 1; store(KEY_TABS, JSON.stringify(seen));
      var n = MINI[tab].length;
      showHint({
        title: 'New here?', text: 'Quick tour of ' + (TAB_NAMES[tab] || 'this tab') + ' (' + n + ' steps).',
        primary: 'Show me', secondary: 'Not now', onPrimary: function () { startTab(tab); }
      });
    } catch (e) { /* ignore */ }
  }
  function onTab(e) {
    if (!ready || suppress) return;
    closeHint();
    var tab = e && e.detail && e.detail.tab;
    if (tab) setTimeout(function () { var cw = CW(); if (cw && cw.S && cw.S.tab === tab) offerTab(tab); }, 500);
  }
  function onWhatIf(e) {
    try {
      if (!e || !e.detail || e.detail.action !== 'apply' || T || !mainDone || store(KEY_WI) === '1') return;
      store(KEY_WI, '1');
      setTimeout(function () {
        if (T) return;
        showHint({ title: 'Your change, shown', text: 'This shows what your change did. Undo it here.', primary: 'Got it', anchor: ['#whatif-viz-root', '#whatif-dock'] });
      }, 700);
    } catch (err) { /* ignore */ }
  }
  function onReady() {
    ready = true;
    if (!CW()) return;
    if (!mainDone) { startTimer = setTimeout(function () { if (!T && !mainDone) startMain(); }, 700); }
    else setTimeout(function () { var cw = CW(); if (cw && cw.S && !T) offerTab(cw.S.tab); }, 900);
  }

  function init() {
    try {
      document.addEventListener('crosswalk:ready', onReady);
      document.addEventListener('crosswalk:tab', onTab);
      document.addEventListener('crosswalk:whatif', onWhatIf);
      document.addEventListener('click', function (e) {
        var b = e.target && e.target.closest && e.target.closest('#tour-start');
        if (b) { e.preventDefault(); startMain(); }
      });
      if (window.CW && document.readyState !== 'loading' && $('#panel-coverage .card, #panel-coverage .fam')) onReady();
    } catch (e) { /* ignore */ }
  }

  window.CWTour = { start: startMain, startTab: startTab, isActive: function () { return !!T; }, reset: wipe };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
