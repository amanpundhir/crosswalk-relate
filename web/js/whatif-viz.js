/* Crosswalk what-if simulation view. Classic script; hooks in through window.CW and the crosswalk:* events.
 * Renders into #whatif-viz-root. Read-only on the graph (MATCH queries only). Never throws into the page. */
(() => {
  'use strict';

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;
  const reduced = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const CW = () => window.CW || null;

  const ST = { covered: 'Covered', inherited: 'Inherited', gap: 'Gap' };
  const MAX_REQ = 8;       // requirement chips per control before "+n more"
  const MAX_CTRL = 12;     // control chips before "+n more"

  const st = { root: null, body: null, live: null, idx: -1, open: false, flash: '', flashTimer: 0, tweenId: 0, anim: 0, lastChanges: [] };

  // ------------------------------------------------------------------------------------------
  // small helpers
  // ------------------------------------------------------------------------------------------
  const sid = (id) => { try { return CW().A.shortId(id); } catch { return id; } };
  const nameOf = (id) => { try { return CW().S.names[id] || ''; } catch { return ''; } };
  const fwOf = (id) => { const m = /^(800-53|800-171|CSF):/.exec(id); return m ? m[1] : null; };
  const rows = (cy, params) => { try { return CW().S.g.run(cy, params || {}).rows || []; } catch (e) { return []; } };
  const asOf = () => { try { return CW().S.asOf; } catch { return ''; } };

  function pill(status) {
    return `<span class="wv-pill wv-${status}">${esc(ST[status] || status)}</span>`;
  }
  function trans(from, to) {
    if (from === to) return pill(to);
    return `<span class="wv-trans">${pill(from)}<span class="wv-arr" aria-hidden="true">&rarr;</span><span class="wv-sr"> to </span>${pill(to)}</span>`;
  }

  // ------------------------------------------------------------------------------------------
  // data for each story (read-only queries)
  // ------------------------------------------------------------------------------------------
  function expireModel(w) {
    const links = rows(
      `MATCH (e:Evidence {id: $id})-[:PROVES]->(c:Control)
       OPTIONAL MATCH (c)-[:SATISFIES]->(r:Requirement)
       RETURN c.id AS c, r.id AS r`, { id: w.id });
    const others = new Map(rows(
      `MATCH (e:Evidence {id: $id})-[:PROVES]->(c:Control)
       OPTIONAL MATCH (c)<-[:PROVES]-(o:Evidence) WHERE o.id <> $id AND o.expires_at > date($as_of)
       RETURN c.id AS c, count(o) AS n`, { id: w.id, as_of: asOf() }).map((r) => [r.c, r.n]));
    const aff = new Map((w.affected || []).map((a) => [a.id, a]));
    const byCtrl = new Map();
    for (const l of links) {
      if (!byCtrl.has(l.c)) byCtrl.set(l.c, { id: l.c, others: others.get(l.c) ?? 0, reqs: [], other: 0 });
      if (!l.r) continue;
      const b = byCtrl.get(l.c);
      if (fwOf(l.r) === '800-171') b.reqs.push(l.r); else b.other++;
    }
    const reached = new Set();
    const ctrls = [...byCtrl.values()].map((b) => {
      const seq = b.reqs.slice().sort((x, y) => (aff.has(y) - aff.has(x)) || x.localeCompare(y, 'en', { numeric: true }));
      seq.forEach((r) => reached.add(r));
      return { ...b, reqs: seq };
    }).sort((a, b) => (a.others > 0) - (b.others > 0) || a.id.localeCompare(b.id, 'en', { numeric: true }));
    const knock = (w.affected || []).filter((a) => !reached.has(a.id));
    return { ctrls, knock };
  }

  function removeModel(w) {
    const ids = w.controls || [];
    const sat = ids.length ? rows(
      `MATCH (c:Control)-[:SATISFIES]->(r:Requirement) WHERE c.id IN $ids RETURN c.id AS c, r.id AS r`, { ids }) : [];
    const depSet = new Set((w.dependent || []).map((d) => d.requirement));
    const per = new Map(ids.map((c) => [c, []]));
    for (const s of sat) per.get(s.c)?.push(s.r);
    const unowned = rows(`MATCH (c:Control {adopted: true}) WHERE NOT EXISTS { MATCH (:Person)-[:OWNS]->(c) } RETURN c.id AS id`).map((r) => r.id);
    const unSet = new Set(unowned);
    const nowNoOwner = unowned.length;
    const beforeNoOwner = nowNoOwner - ids.filter((c) => unSet.has(c)).length;
    const ctrls = ids.map((c) => ({
      id: c,
      reqs: per.get(c).filter((r) => depSet.has(r)).sort((x, y) => x.localeCompare(y, 'en', { numeric: true })),
      total: per.get(c).length,
    })).sort((a, b) => b.reqs.length - a.reqs.length || a.id.localeCompare(b.id, 'en', { numeric: true }));
    return { ctrls, beforeNoOwner, nowNoOwner, dependent: [...depSet].sort((x, y) => x.localeCompare(y, 'en', { numeric: true })) };
  }

  // ------------------------------------------------------------------------------------------
  // pieces of markup
  // ------------------------------------------------------------------------------------------
  const step = (n, title, inner, delay) =>
    `<section class="wv-step" style="--d:${delay}ms"><h4 class="wv-step-h"><span class="wv-num" aria-hidden="true">${n}</span>${esc(title)}</h4>${inner}</section>`;

  function reqChip(id, a) {
    const label = sid(id);
    const t = nameOf(id);
    if (!a) return `<button type="button" class="wv-req wv-same" data-wv="open" data-req="${esc(id)}"${t ? ` title="${esc(t)}"` : ''}><span class="wv-req-id">${esc(label)}</span><span class="wv-req-note">no change</span></button>`;
    return `<button type="button" class="wv-req wv-to-${a.to}" data-wv="open" data-req="${esc(id)}"${t ? ` title="${esc(t)}"` : ''}><span class="wv-req-id">${esc(label)}</span>${trans(a.from, a.to)}</button>`;
  }

  function reqList(ids, aff, max = MAX_REQ) {
    const shown = ids.slice(0, max).map((r) => reqChip(r, aff.get(r))).join('');
    const more = ids.length > max ? `<span class="wv-more">+${ids.length - max} more</span>` : '';
    return shown + more;
  }

  function barRow(label, vals, id) {
    const total = (vals.covered + vals.inherited + vals.gaps) || 1;
    const pct = (n) => ((n / total) * 100).toFixed(2);
    return `<div class="wv-barrow"><span class="wv-barlabel">${esc(label)}</span>`
      + `<div class="wv-bar" role="img" aria-label="${esc(label)}: ${vals.covered} covered, ${vals.inherited} inherited, ${vals.gaps} gaps"${id ? ` id="${id}"` : ''}>`
      + `<span class="wv-seg wv-covered" style="width:${pct(vals.covered)}%"></span><span class="wv-seg wv-inherited" style="width:${pct(vals.inherited)}%"></span><span class="wv-seg wv-gap" style="width:${pct(vals.gaps)}%"></span></div></div>`;
  }

  function totals(w) {
    const b = w.before; const a = w.after;
    const cell = (key, label, cls) => {
      const d = a[key] - b[key];
      const dc = d === 0 ? 'wv-d0' : (key === 'gaps' ? (d > 0 ? 'wv-dbad' : 'wv-dgood') : (key === 'covered' ? (d < 0 ? 'wv-dbad' : 'wv-dgood') : 'wv-dneutral'));
      return `<div class="wv-tot ${cls}"><span class="wv-tot-l">${label}</span><span class="wv-tot-n">${b[key]} <span class="wv-arr" aria-hidden="true">&rarr;</span><span class="wv-sr"> to </span> <b class="wv-count ${dc}" data-from="${b[key]}" data-to="${a[key]}">${a[key]}</b></span></div>`;
    };
    return `<div class="wv-bars">${barRow('Before', b)}${barRow('After', a, 'wv-after-bar')}</div>`
      + `<div class="wv-tots">${cell('covered', 'Covered', 'wv-covered')}${cell('inherited', 'Inherited', 'wv-inherited')}${cell('gaps', 'Gaps', 'wv-gap')}</div>`
      + `<p class="wv-fine">800-171 requirements, demo date ${esc(asOf())}.</p>`;
  }

  function consequence(w) {
    if (w.kind === 'remove') {
      const n = (w.controls || []).length; const m = (w.dependent || []).length;
      const first = (w.name || 'This person').split(' ')[0];
      if (!n) return `${first} didn't solely own any control, so nothing loses its owner. Coverage is unchanged.`;
      return `Coverage numbers don't change when ${first} leaves, but ownership does: ${plural(n, 'control')} now ${n === 1 ? 'has' : 'have'} no owner, and ${plural(m, 'requirement')} depend${m === 1 ? 's' : ''} on ${n === 1 ? 'it' : 'them'} alone.`;
    }
    const aff = w.affected || [];
    const lost = aff.filter((x) => x.from === 'covered' && x.to !== 'covered');
    const still = lost.filter((x) => x.to === 'inherited').length;
    const gaps = aff.filter((x) => x.to === 'gap' && x.from !== 'gap').length;
    if (!aff.length) return `Nothing changes: other evidence still backs every control ${w.id} proved.`;
    if (!lost.length) return `${plural(aff.length, 'requirement')} changed status, but none lost its proof.`;
    return `${plural(lost.length, 'requirement')} ${lost.length === 1 ? 'no longer has' : 'no longer have'} proof; ${still} ${still === 1 ? 'is' : 'are'} still met through another framework, ${gaps} ${gaps === 1 ? 'is' : 'are'} now a gap.`;
  }

  function expireStory(w, model) {
    const aff = new Map((w.affected || []).map((a) => [a.id, a]));
    const t = nameOf(w.id);
    const s1 = `<div class="wv-card wv-ev wv-expiring"><span class="wv-card-kind">Evidence</span><b class="wv-card-id">${esc(w.id)}</b>`
      + (t ? `<span class="wv-card-t">${esc(t)}</span>` : '')
      + `<span class="wv-stamp"><span class="wv-stamp-ok">valid</span><span class="wv-stamp-bad">expired</span></span></div>`
      + `<p class="wv-line">You marked this proof as out of date (demo date ${esc(asOf())}).</p>`;
    const nCtrl = model.ctrls.length;
    const orphan = model.ctrls.filter((c) => c.others === 0).length;
    let branches = model.ctrls.map((c) => {
      const reqs = c.reqs.length ? reqList(c.reqs, aff) : '';
      const extra = c.other ? `<span class="wv-note">${c.other === 1 ? '1 requirement' : c.other + ' requirements'} in other frameworks</span>` : '';
      const proof = c.others > 0 ? `<span class="wv-tag wv-tag-ok">still proven by ${plural(c.others, 'other item')}</span>` : `<span class="wv-tag wv-tag-bad">no proof left</span>`;
      return `<div class="wv-branch ${c.others > 0 ? 'wv-safe' : 'wv-lost'}"><div class="wv-branch-ctrl"><span class="wv-chip wv-ctrl-chip" title="${esc(nameOf(c.id))}">${esc(sid(c.id))}</span>${proof}</div>`
        + `<span class="wv-flow" aria-hidden="true"></span><div class="wv-branch-reqs">${reqs || ''}${extra}${!reqs && !extra ? '<span class="wv-note">maps to no requirement</span>' : ''}</div></div>`;
    }).join('');
    if (!nCtrl) branches = '<p class="wv-line">This evidence is not attached to any control, so nothing depends on it.</p>';
    const backed = nCtrl - orphan;
    const proofTxt = !nCtrl ? '' : orphan === nCtrl ? (nCtrl === 1 ? '; it has no other proof left' : '; none has other proof left') : backed === nCtrl ? '; all of them still have other proof' : `; ${backed} still ${backed === 1 ? 'has' : 'have'} other proof, ${orphan} ${orphan === 1 ? 'has' : 'have'} none left`;
    const s2 = `<p class="wv-line">It was proof for ${plural(nCtrl, 'control')}${proofTxt}. Each control feeds the requirements on its right.</p>${branches.length ? `<div class="wv-branches">${branches}</div>` : ''}`;
    const knock = model.knock.length
      ? `<div class="wv-knock"><span class="wv-note">Also changed, through another framework:</span> ${model.knock.slice(0, 12).map((a) => reqChip(a.id, a)).join('')}${model.knock.length > 12 ? `<span class="wv-more">+${model.knock.length - 12} more</span>` : ''}</div>` : '';
    return [
      step(1, 'The evidence expires', s1, 0),
      step(2, 'Controls lose their proof', s2, 450),
      knock ? step(3, 'Requirements change status', knock, 900) : '',
      step(knock ? 4 : 3, 'What it does to the totals', totals(w), 1100),
    ].join('');
  }

  function removeStory(w, model) {
    const first = (w.name || w.id).split(' ')[0];
    const s1 = `<div class="wv-card wv-person wv-leaving"><span class="wv-card-kind">Person</span><b class="wv-card-id">${esc(w.name || w.id)}</b><span class="wv-stamp"><span class="wv-stamp-ok">on the team</span><span class="wv-stamp-bad">removed</span></span></div>`
      + `<p class="wv-line">${esc(first)} is gone from the graph. Nothing is saved: Undo brings ${esc(first)} back.</p>`;
    const n = model.ctrls.length;
    const depSet = new Set(model.dependent);
    const noAff = new Map();
    let ctrls = model.ctrls.slice(0, MAX_CTRL).map((c) => {
      const reqs = c.reqs.length ? c.reqs.slice(0, MAX_REQ).map((r) => `<button type="button" class="wv-req wv-to-owner" data-wv="open" data-req="${esc(r)}"${nameOf(r) ? ` title="${esc(nameOf(r))}"` : ''}><span class="wv-req-id">${esc(sid(r))}</span><span class="wv-req-note">${esc(fwLabel(r))} · no owner</span></button>`).join('') + (c.reqs.length > MAX_REQ ? `<span class="wv-more">+${c.reqs.length - MAX_REQ} more</span>` : '') : '<span class="wv-note">its requirements are also covered by other controls</span>';
      return `<div class="wv-branch wv-lost"><div class="wv-branch-ctrl"><span class="wv-chip wv-ctrl-chip" title="${esc(nameOf(c.id))}">${esc(sid(c.id))}</span><span class="wv-tag wv-tag-bad">no owner</span></div><span class="wv-flow" aria-hidden="true"></span><div class="wv-branch-reqs">${reqs}</div></div>`;
    }).join('');
    void noAff; void depSet;
    if (n > MAX_CTRL) ctrls += `<p class="wv-more">+${n - MAX_CTRL} more controls without an owner</p>`;
    if (!n) ctrls = '';
    const s2 = n ? `<p class="wv-line">${esc(first)} was the only owner of ${plural(n, 'control')}. They now have nobody responsible, and the requirements each one supports (that depend on it alone) are shown on the right.</p><div class="wv-branches">${ctrls}</div>`
      : `<p class="wv-line">${esc(first)} wasn't the sole owner of any control, so nothing is left without an owner.</p>`;
    const gauge = `<div class="wv-gauge"><span class="wv-gauge-l">Controls with no owner</span><span class="wv-gauge-n"><span>${model.beforeNoOwner}</span> <span class="wv-arr" aria-hidden="true">&rarr;</span><span class="wv-sr"> to </span> <b class="wv-count ${model.nowNoOwner > model.beforeNoOwner ? 'wv-dbad' : 'wv-d0'}" data-from="${model.beforeNoOwner}" data-to="${model.nowNoOwner}">${model.nowNoOwner}</b></span></div>`;
    const s3 = `<div class="wv-bars">${barRow('Coverage now', w.after)}</div>`
      + `<div class="wv-tots"><div class="wv-tot wv-covered"><span class="wv-tot-l">Covered</span><span class="wv-tot-n">${w.after.covered} <span class="wv-same-tag">unchanged</span></span></div><div class="wv-tot wv-inherited"><span class="wv-tot-l">Inherited</span><span class="wv-tot-n">${w.after.inherited} <span class="wv-same-tag">unchanged</span></span></div><div class="wv-tot wv-gap"><span class="wv-tot-l">Gaps</span><span class="wv-tot-n">${w.after.gaps} <span class="wv-same-tag">unchanged</span></span></div></div>`
      + gauge
      + `<p class="wv-fine">Coverage is about proof; people don't change proof. Ownership risk is what moved. 800-171, demo date ${esc(asOf())}.</p>`;
    return [step(1, 'The person leaves', s1, 0), step(2, 'Controls lose their owner', s2, 450), step(3, 'What changes, and what does not', s3, 1000)].join('');
  }

  const fwLabel = (id) => ({ '800-171': '800-171', '800-53': '800-53', CSF: 'CSF' }[fwOf(id)] || '');

  // ------------------------------------------------------------------------------------------
  // rendering
  // ------------------------------------------------------------------------------------------
  function idleCard(restored) {
    return `<div class="wv-idle${restored ? ' wv-restored' : ''}">`
      + (restored ? `<p class="wv-restored-msg"><span aria-hidden="true">&#10003;</span> Restored. ${esc(restored)}</p>` : '')
      + `<div class="wv-idle-main"><div class="wv-idle-txt"><h3 class="wv-idle-h" id="wv-idle-h">Try a simulation</h3>`
      + `<p class="wv-idle-p">Change something and watch what breaks. Nothing is saved: reload the page or press Undo to go back.</p></div>`
      + `<div class="wv-idle-btns"><button type="button" class="wv-btn wv-btn-primary" data-wv="expire">Expire evidence</button><button type="button" class="wv-btn" data-wv="remove">Remove a person</button></div></div></div>`;
  }

  function compactBar(changes) {
    const last = changes[changes.length - 1];
    return `<div class="wv-idle wv-compact"><div class="wv-idle-main"><div class="wv-idle-txt"><h3 class="wv-idle-h">Simulation running</h3><p class="wv-idle-p">${plural(changes.length, 'change')} applied. Latest: ${esc(last.label)}.</p></div>`
      + `<div class="wv-idle-btns"><button type="button" class="wv-btn wv-btn-primary" data-wv="show">Show what happened</button><button type="button" class="wv-btn" data-wv="expire">Expire evidence</button><button type="button" class="wv-btn" data-wv="remove">Remove a person</button></div></div></div>`;
  }

  function panel(changes, idx) {
    const w = changes[idx];
    const model = w.kind === 'remove' ? removeModel(w) : expireModel(w);
    const story = w.kind === 'remove' ? removeStory(w, model) : expireStory(w, model);
    const heading = w.kind === 'remove' ? `Simulation: ${w.name || w.id} leaves` : `Simulation: ${w.id} expires`;
    const tabs = changes.length > 1
      ? `<div class="wv-tabs" role="group" aria-label="Changes in this simulation">${changes.map((c, i) => `<button type="button" class="wv-tab" data-wv="pick" data-i="${i}" aria-pressed="${i === idx}">${i + 1}. ${esc(c.label)}</button>`).join('')}</div>` : '';
    const first = changes.length > 1 ? `<p class="wv-fine">All ${changes.length} changes together: Covered ${changes[0].before.covered} &rarr; ${changes[changes.length - 1].after.covered}, Inherited ${changes[0].before.inherited} &rarr; ${changes[changes.length - 1].after.inherited}, Gaps ${changes[0].before.gaps} &rarr; ${changes[changes.length - 1].after.gaps}.</p>` : '';
    // actions
    let openReq = null; let paths = [];
    if (w.kind === 'remove') {
      openReq = model.dependent.find((r) => fwOf(r) === '800-171') || model.dependent[0] || null;
      for (const c of model.ctrls.slice(0, 6)) for (const r of c.reqs.slice(0, 3)) paths.push({ nodes: ['Control:' + c.id, 'Requirement:' + r], rels: ['SATISFIES'] });
    } else {
      const a = (w.affected || []).find((x) => fwOf(x.id) === '800-171') || (w.affected || [])[0];
      openReq = a ? a.id : null;
      const seen = new Set();
      for (const c of model.ctrls) for (const r of c.reqs) {
        if (!(w.affected || []).some((x) => x.id === r)) continue;
        const key = c.id + r; if (seen.has(key)) continue; seen.add(key);
        paths.push({ nodes: ['Evidence:' + w.id, 'Control:' + c.id, 'Requirement:' + r], rels: ['PROVES', 'SATISFIES'] });
      }
      if (!paths.length) for (const c of model.ctrls.slice(0, 4)) paths.push({ nodes: ['Evidence:' + w.id, 'Control:' + c.id], rels: ['PROVES'] });
    }
    const showPaths = paths.length && CW() && typeof CW().goPaths === 'function';
    const actions = `<div class="wv-actions">`
      + (openReq ? `<button type="button" class="wv-btn wv-btn-primary" data-wv="open" data-req="${esc(openReq)}">Open requirement ${esc(sid(openReq))}</button>` : '')
      + (showPaths ? `<button type="button" class="wv-btn" data-wv="graph" data-paths="${esc(JSON.stringify(paths))}">Show on graph</button>` : '')
      + `<button type="button" class="wv-btn" data-wv="undo" data-i="${idx}">Undo this change</button>`
      + `<button type="button" class="wv-btn wv-btn-quiet" data-wv="replay">Replay</button>`
      + `<button type="button" class="wv-btn wv-btn-quiet" data-wv="close">Close</button></div>`;
    return `<section class="wv-panel wv-kind-${w.kind}" aria-labelledby="wv-h">`
      + `<header class="wv-head"><h3 class="wv-title" id="wv-h" tabindex="-1">${esc(heading)}</h3><span class="wv-badge">Not saved</span></header>`
      + (st.flash ? `<p class="wv-flash">${esc(st.flash)}</p>` : '')
      + tabs
      + `<p class="wv-verdict">${esc(consequence(w))}</p>`
      + `<div class="wv-story">${story}</div>${first}${actions}</section>`;
  }

  function currentChanges() { try { return CW().S.whatIf.map((w) => w); } catch { return []; } }

  function render(opts = {}) {
    if (!st.body) return;
    const changes = opts.changes || currentChanges();
    st.lastChanges = changes;
    clearTimeout(st.flashTimer);
    cancelAnimationFrame(st.tweenId);
    if (!changes.length) {
      st.body.innerHTML = idleCard(opts.restored || '');
      if (opts.restored) st.flashTimer = setTimeout(() => { if (!currentChanges().length) st.body.innerHTML = idleCard(''); }, 6000);
      return;
    }
    if (!st.open) { st.body.innerHTML = compactBar(changes); return; }
    if (st.idx < 0 || st.idx >= changes.length) st.idx = changes.length - 1;
    try {
      st.body.innerHTML = panel(changes, st.idx);
    } catch (e) {
      console.warn('whatif-viz', e);
      st.body.innerHTML = compactBar(changes);
      return;
    }
    playAnimation(opts.focus);
    if (st.flash) st.flashTimer = setTimeout(() => { st.flash = ''; st.body.querySelector('.wv-flash')?.remove(); }, 5000);
  }

  function playAnimation(focus) {
    const panelEl = st.body.querySelector('.wv-panel');
    if (!panelEl) return;
    if (focus) {
      const h = panelEl.querySelector('#wv-h');
      try { h && h.focus({ preventScroll: true }); } catch { /* ignore */ }
    }
    const after = panelEl.querySelector('#wv-after-bar');
    const counts = [...panelEl.querySelectorAll('.wv-count')];
    if (reduced()) { panelEl.classList.add('wv-static'); return; }
    // the "After" bar starts at the Before widths, then morphs
    const segs = after ? [...after.children] : [];
    const finalW = segs.map((s) => s.style.width);
    const beforeSegs = panelEl.querySelectorAll('.wv-bars .wv-barrow:first-child .wv-seg');
    segs.forEach((s, i) => { s.style.transition = 'none'; s.style.width = beforeSegs[i] ? beforeSegs[i].style.width : finalW[i]; });
    counts.forEach((c) => { c.textContent = c.dataset.from; });
    const anim = ++st.anim;
    panelEl.classList.remove('wv-play'); void panelEl.offsetWidth; panelEl.classList.add('wv-play');
    setTimeout(() => {
      if (anim !== st.anim) return;
      segs.forEach((s, i) => { s.style.transition = ''; s.style.width = finalW[i]; });
      const t0 = performance.now(); const dur = 900;
      const tick = (now) => {
        if (anim !== st.anim) return;
        const p = Math.min(1, (now - t0) / dur); const e = 1 - Math.pow(1 - p, 3);
        counts.forEach((c) => { const f = +c.dataset.from; const t = +c.dataset.to; c.textContent = Math.round(f + (t - f) * e); });
        if (p < 1) st.tweenId = requestAnimationFrame(tick);
      };
      st.tweenId = requestAnimationFrame(tick);
    }, 1100);
    // on a hidden tab timers still fire; make sure the final numbers are right
    setTimeout(() => { if (anim === st.anim) counts.forEach((c) => { c.textContent = c.dataset.to; }); }, 2300);
  }

  function reveal() {
    const el = st.body && st.body.querySelector('.wv-panel');
    if (!el) return;
    try { el.scrollIntoView({ block: 'nearest', behavior: reduced() ? 'auto' : 'smooth' }); } catch { /* ignore */ }
  }

  // ------------------------------------------------------------------------------------------
  // events
  // ------------------------------------------------------------------------------------------
  function say(text) { if (st.live) { st.live.textContent = ''; setTimeout(() => { st.live.textContent = text; }, 30); } }

  function onWhatIf(ev) {
    try {
      const d = ev.detail || {};
      const changes = d.changes || [];
      if (d.action === 'apply' && d.last) {
        st.open = true; st.idx = changes.length - 1; st.flash = '';
        render({ changes, focus: true });
        say(consequence(d.last));
        setTimeout(reveal, 150);
      } else if (d.action === 'undo' || d.action === 'reset') {
        if (!changes.length) {
          st.open = false; st.idx = -1;
          const b = currentCover();
          render({ changes, restored: d.action === 'reset' ? `All changes undone.${b}` : `Change undone.${b}` });
          say(d.action === 'reset' ? 'All changes undone. Numbers restored.' : 'Change undone. Numbers restored.');
        } else {
          st.idx = changes.length - 1;
          st.flash = 'Restored: the change you undid is no longer applied. Showing the latest one left.';
          render({ changes, focus: st.open });
          say('Change undone. Numbers restored.');
        }
      }
    } catch (e) { console.warn('whatif-viz', e); }
  }

  function currentCover() {
    try {
      const c = CW().A.coverage(CW().S.g, { framework: '800-171', asOf: asOf() });
      return ` Covered ${c.covered}, inherited ${c.inherited}, gaps ${c.gaps}.`;
    } catch { return ''; }
  }

  function onClick(ev) {
    const el = ev.target.closest && ev.target.closest('[data-wv]');
    if (!el || !st.root.contains(el)) return;
    const cw = CW(); if (!cw) return;
    const act = el.dataset.wv;
    try {
      if (act === 'expire') cw.openExpire();
      else if (act === 'remove') cw.openRemove();
      else if (act === 'open') cw.openRequirement(el.dataset.req);
      else if (act === 'graph') cw.goPaths(JSON.parse(el.dataset.paths));
      else if (act === 'undo') cw.undoWhatIf(Number(el.dataset.i));
      else if (act === 'close') { st.open = false; render({}); st.body.querySelector('[data-wv="show"], [data-wv="expire"]')?.focus({ preventScroll: true }); }
      else if (act === 'show') { st.open = true; st.idx = -1; render({ focus: true }); }
      else if (act === 'replay') { render({ focus: false }); }
      else if (act === 'pick') { st.idx = Number(el.dataset.i); st.flash = ''; render({ focus: false }); st.body.querySelector(`.wv-tab[data-i="${st.idx}"]`)?.focus({ preventScroll: true }); }
    } catch (e) { console.warn('whatif-viz', e); }
  }

  function onKey(ev) {
    if (ev.key === 'Escape' && st.open && st.body.querySelector('.wv-panel') && st.root.contains(document.activeElement)) {
      st.open = false; render({});
      st.body.querySelector('[data-wv="show"]')?.focus({ preventScroll: true });
    }
  }

  function start() {
    if (st.root || !window.CW) return;
    const root = document.getElementById('whatif-viz-root');
    if (!root) return;
    try {
      st.root = root;
      root.classList.add('wv');
      root.innerHTML = '<div class="wv-live wv-sr" role="status" aria-live="polite"></div><div class="wv-body"></div>';
      st.live = root.querySelector('.wv-live');
      st.body = root.querySelector('.wv-body');
      root.addEventListener('click', onClick);
      root.addEventListener('keydown', onKey);
      document.addEventListener('crosswalk:whatif', onWhatIf);
      const cur = currentChanges();
      if (cur.length) { st.open = false; }
      render({ changes: cur });
    } catch (e) { console.warn('whatif-viz', e); }
  }

  document.addEventListener('crosswalk:ready', start);
  if (window.CW) start();
  else document.addEventListener('DOMContentLoaded', () => { if (window.CW) start(); });
})();
