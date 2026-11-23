// Crosswalk explorer: static page, Relate WASM in memory, no backend.
import init, { RelateDb } from '../vendor/relate/relate.js';
import { GraphDb } from './graphdb.js';
import * as A from './analysis.js';
import { GraphView, LEGEND } from './graphview.js';
import { renderScorecard } from './scorecard.js';

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const plural = (n, one, many = one + 's') => `${n} ${n === 1 ? one : many}`;
const TABS = ['coverage', 'adopt', 'blast', 'graph', 'agent', 'scorecard'];

const S = {
  g: null, meta: null, asOf: null, tab: 'coverage', rev: 0, rendered: {},
  whatIf: [], names: {}, base: {}, liveCatch: null, scorecard: undefined, graphView: null, graphStale: true,
  cov: { framework: '800-171', audit: '', gapsOnly: false, expandAll: false },
  adopt: { framework: '800-171' },
  blast: { window: '30', custom: '', person: 'P-dana-okafor' },
};

// ---------------------------------------------------------------------------------------------
// small view helpers
// ---------------------------------------------------------------------------------------------

const refId = (ref) => A.splitRef(ref).id;
const nameOf = (id) => S.names[id] || '';

function tag(id, cls = '') {
  const title = nameOf(id);
  return `<span class="tag ${cls}"${title ? ` title="${esc(title)}"` : ''}>${esc(A.shortId(id))}</span>`;
}

function chain(nodes, rels, badIds = []) {
  const bad = new Set(badIds);
  return `<span class="chain">${nodes.map((n, i) => {
    const id = refId(n);
    const t = tag(id, bad.has(id) ? (id.startsWith('PR-') ? 'warn' : 'bad') : '');
    if (i >= rels.length) return t;
    const rev = rels[i].endsWith('<-');
    const type = rev ? rels[i].slice(0, -2) : rels[i];
    return `${t}<span class="arrow" title="${esc(type)}" aria-label="${esc(type)}">${rev ? '&larr;' : '&rarr;'}</span>`;
  }).join('')}</span>`;
}

function pathButton(paths, label = 'Show on graph') {
  return `<button type="button" class="linkbtn" data-act="show-paths" data-paths="${esc(JSON.stringify(paths))}">${esc(label)}</button>`;
}

const statusPill = (s) => `<span class="pill ${s}">${s === 'gap' ? 'gap' : s}</span>`;

function bar(c, i, g, big = false) {
  const total = c + i + g || 1;
  const pct = (n) => ((n / total) * 100).toFixed(2);
  return `<div class="bar${big ? ' big' : ''}" role="img" aria-label="${c} covered, ${i} inherited, ${g} gaps">`
    + `<span class="s-covered" style="width:${pct(c)}%"></span><span class="s-inherited" style="width:${pct(i)}%"></span><span class="s-gap" style="width:${pct(g)}%"></span></div>`;
}

function deltaTxt(now, was) {
  return was === undefined || was === now ? '' : ` <span class="muted">(was ${was})</span>`;
}

function select(id, options, value, label) {
  return `<label>${esc(label)}<select id="${id}">${options.map(([v, t]) => `<option value="${esc(v)}"${String(v) === String(value) ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select></label>`;
}

// ---------------------------------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------------------------------

async function getText(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.text();
}
async function getJsonOrNull(url) {
  try {
    const r = await fetch(url);
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}
const tick = () => new Promise((r) => setTimeout(r, 0));

function fatal(msg) {
  $('#loading').hidden = true;
  const el = $('#fatal');
  el.hidden = false;
  el.innerHTML = msg;
}

async function boot() {
  if (location.protocol === 'file:') {
    return fatal('This page needs to be served over http (browsers will not load WebAssembly from <code>file://</code>). From the repo root run <code>python -m http.server -d web 8000</code> and open <code>http://localhost:8000</code>.');
  }
  try {
    const meta = JSON.parse(await getText('data/meta.json'));
    const [script, ...qs] = await Promise.all([getText('data/graph.cypher'), ...meta.queries.map((n) => getText(`queries/${n}.cypher`)), init()]);
    $('#loading-text').textContent = `Building the graph in your browser (${meta.total_nodes.toLocaleString()} nodes, ${meta.total_relationships.toLocaleString()} relationships)…`;
    await tick();
    const g = new GraphDb(RelateDb);
    g.setScript(script);
    g.setQueries(Object.fromEntries(meta.queries.map((n, i) => [n, qs[i]])));
    g.load();
    S.g = g;
    S.meta = meta;
    S.asOf = A.readAsOf(g);
    loadNames();
    computeBase();
    S.liveCatch = meta.has_live_catch ? await getJsonOrNull('data/live-catch.json') : null;
  } catch (e) {
    console.error(e);
    return fatal(`Could not start the explorer: <code>${esc(e.message || e)}</code>. Check that <code>web/data/graph.cypher</code> exists (<code>python -m crosswalk.export_web</code>) and that the page is served over http.`);
  }
  $('#loading').hidden = true;
  $('#asof-chip').textContent = `${S.meta.company || 'Company'} · as of ${S.asOf}`;
  $('#foot-stats').textContent = `Graph: ${S.meta.total_nodes.toLocaleString()} nodes, ${S.meta.total_relationships.toLocaleString()} relationships, built in your browser in ${S.g.loadedMs} ms. Queries are the same Cypher files the CLI runs.`;
  for (const id of ['btn-expire', 'btn-remove', 'btn-reset']) $('#' + id).disabled = false;
  wire();
  const initial = location.hash.slice(1);
  showTab(TABS.includes(initial) ? initial : 'coverage', { push: false });
  refreshChrome();
}

function loadNames() {
  const out = {};
  for (const [label, prop] of [['Control', 'title'], ['Evidence', 'title'], ['Person', 'name'], ['System', 'name'], ['Audit', 'name'], ['Policy', 'name']]) {
    for (const r of S.g.run(`MATCH (n:${label}) RETURN n.id AS id, n.${prop} AS t`).rows) out[r.id] = r.t;
  }
  S.names = { ...S.names, ...out };
}

function computeBase() {
  S.base = {};
  const g = S.g;
  for (const fw of A.FRAMEWORKS) S.base[fw] = pick(A.coverage(g, { framework: fw, asOf: S.asOf }));
  for (const a of S.meta.audits) S.base[a.id] = pick(A.coverage(g, { audit: a.id, asOf: S.asOf }));
  function pick(c) { return { covered: c.covered, inherited: c.inherited, gaps: c.gaps, total: c.total }; }
}

// ---------------------------------------------------------------------------------------------
// chrome: hero KPIs, what-if banner
// ---------------------------------------------------------------------------------------------

function refreshChrome() {
  const c = A.coverage(S.g, { framework: '800-171', asOf: S.asOf });
  const b30 = A.blast(S.g, { asOf: S.asOf, until: A.addDays(S.asOf, 30) });
  const base = S.base['800-171'];
  const kpis = [
    ['covered', 'Covered', c.covered, base.covered, 'Met directly: an approved control with evidence that is still valid.'],
    ['inherited', 'Inherited', c.inherited, base.inherited, 'Not met directly, but a matching requirement in another framework is.'],
    ['gap', 'Gaps', c.gaps, base.gaps, 'No control and no crosswalk neighbour meets these yet.'],
    ['', 'Evidence expiring in 30 days', b30.expiring.length, undefined, 'Items whose proof lapses soon. Open "What breaks" to see what they hold up.'],
  ];
  $('#hero-kpis').innerHTML = kpis.map(([cls, t, n, was, hint]) => `<div class="${cls ? 'c-' + cls : ''}"><dt>${t}</dt><dd>${n}${was !== undefined && was !== n ? ` <small>was ${was}</small>` : ''}</dd><p class="kpi-hint">${hint}</p></div>`).join('')
    + `<div class="kpi-note">The first three count the ${c.total} requirements of NIST SP 800-171 at ${esc(S.asOf)}.</div>`;
  const banner = $('#whatif-banner');
  banner.hidden = !S.whatIf.length;
  if (S.whatIf.length) {
    banner.innerHTML = `<strong>What-if active</strong> (in memory only): ${S.whatIf.map((w) => esc(w.text)).join('; ')}. <button class="linkbtn" type="button" data-act="reset">Reset</button>`;
  }
  const h = $('.top').offsetHeight;
  document.documentElement.style.setProperty('--top-h', h + 'px');
}

function invalidate() {
  S.rev++;
  S.graphStale = true;
  refreshChrome();
  renderTab(S.tab);
}

// ---------------------------------------------------------------------------------------------
// tabs
// ---------------------------------------------------------------------------------------------

function showTab(tab, { push = true } = {}) {
  S.tab = tab;
  for (const t of TABS) {
    const sel = t === tab;
    const btn = $('#tab-' + t);
    btn.setAttribute('aria-selected', String(sel));
    btn.tabIndex = sel ? 0 : -1;
    $('#panel-' + t).hidden = !sel;
  }
  if (push) history.replaceState(null, '', '#' + tab);
  renderTab(tab);
}

function renderTab(tab) {
  if (S.rendered[tab] === S.rev && tab !== 'graph') return;
  const fn = { coverage: renderCoverage, adopt: renderAdopt, blast: renderBlast, graph: renderGraph, agent: renderAgent, scorecard: renderScorecardTab }[tab];
  try {
    fn();
    S.rendered[tab] = S.rev;
  } catch (e) {
    console.error(e);
    $('#panel-' + tab).innerHTML = `<div class="notice error">Something went wrong drawing this tab: <code>${esc(e.message)}</code></div>`;
  }
}

// ---------------------------------------------------------------------------------------------
// Coverage
// ---------------------------------------------------------------------------------------------

function auditFor(framework) {
  return S.meta.audits.find((a) => a.framework === framework) || null;
}

function renderCoverage() {
  const { framework, audit, gapsOnly, expandAll } = S.cov;
  const cov = A.coverage(S.g, { framework: audit ? null : framework, audit: audit || null, asOf: S.asOf });
  const baseKey = audit || cov.framework;
  const base = S.base[baseKey] || {};
  const aud = audit ? S.meta.audits.find((a) => a.id === audit) : auditFor(cov.framework);
  const until = aud ? aud.date : A.addDays(S.asOf, 30);
  const bl = A.blast(S.g, { asOf: S.asOf, until });
  const broken = bl.byFramework[cov.framework] || [];
  const stillMet = broken.filter((b) => b.still_inherited).length;
  const met = cov.covered + cov.inherited;

  const fams = new Map();
  for (const r of cov.requirements) {
    if (!fams.has(r.family_id)) fams.set(r.family_id, { id: r.family_id, title: r.family_title, reqs: [] });
    fams.get(r.family_id).reqs.push(r);
  }
  const famList = [...fams.values()].sort((a, b) => A.nat(a.id, b.id));
  S.famIndex = new Map(famList.map((f) => [f.id, f]));
  const famHtml = famList.map((f) => {
    const shown = gapsOnly ? f.reqs.filter((r) => r.status === 'gap') : f.reqs;
    if (!shown.length) return '';
    const n = (s) => f.reqs.filter((r) => r.status === s).length;
    const open = expandAll;
    return `<details class="fam" data-fam="${esc(f.id)}"${open ? ' open' : ''}>
      <summary><div class="fam-row"><span class="name"><b>${esc(A.shortId(f.id).replace(/^.*:/, ''))}</b> ${esc(f.title)}</span>
        <span class="num covered" title="covered">${n('covered')}</span><span class="num inherited" title="inherited">${n('inherited')}</span><span class="num gap" title="gaps">${n('gap')}</span>
        ${bar(n('covered'), n('inherited'), n('gap'))}</div></summary>
      <div class="reqs" data-filled="${open ? '1' : ''}">${open ? reqListHtml(shown) : ''}</div></details>`;
  }).join('');

  const auditOpts = [['', 'Whole framework'], ...S.meta.audits.map((a) => [a.id, `${a.id} · ${a.date}${a.scope_baseline ? ' · ' + a.scope_baseline + ' baseline' : ''}`])];
  $('#panel-coverage').innerHTML = `
    <div class="card">
      <div class="controls">
        ${select('cov-fw', A.FRAMEWORKS.map((f) => [f, A.FRAMEWORK_LABEL[f]]), cov.framework, 'Framework')}
        ${select('cov-audit', auditOpts, audit, 'Audit')}
        <label class="check"><input type="checkbox" id="cov-gaps"${gapsOnly ? ' checked' : ''}> Show gaps only</label>
        <button type="button" class="btn small" data-act="toggle-expand">${expandAll ? 'Collapse all' : 'Expand all'}</button>
      </div>
      <div style="margin-top:1rem">
        <div class="row-main"><h2 class="grow">${esc(A.FRAMEWORK_LABEL[cov.framework])}${cov.baseline ? ` <span class="muted">(${esc(cov.baseline)} baseline)</span>` : ''}</h2>
          <b style="font-size:1.4rem">${cov.total ? Math.round((met / cov.total) * 100) : 0}%</b> <span class="muted">met, counting inherited</span></div>
        ${bar(cov.covered, cov.inherited, cov.gaps, true)}
        <div class="legend-row"><span><i class="dot covered"></i>Covered directly</span><span><i class="dot inherited"></i>Inherited through the crosswalk</span><span><i class="dot gap"></i>Gap</span></div>
      </div>
      <div class="stats">
        <div class="stat"><b>${cov.total}</b><span>Requirements in scope</span><small>The rules this framework or audit asks you to meet.</small></div>
        <div class="stat"><b style="color:var(--covered)">${cov.covered}${deltaTxt(cov.covered, base.covered)}</b><span>Covered</span><small>Met directly, with valid evidence.</small></div>
        <div class="stat"><b style="color:var(--inherited)">${cov.inherited}${deltaTxt(cov.inherited, base.inherited)}</b><span>Inherited</span><small>Met through another framework. You can adopt it.</small></div>
        <div class="stat"><b style="color:var(--gap)">${cov.gaps}${deltaTxt(cov.gaps, base.gaps)}</b><span>Gaps</span><small>Nothing meets these yet.</small></div>
        <div class="stat"><b>${bl.expiring.length}</b><span>Evidence expiring</span><small>Items that lapse before ${esc(until)}${aud ? ' (' + esc(aud.id) + ')' : ''}.</small></div>
        <div class="stat"><b style="color:var(--${broken.length ? 'warn' : 'covered'})">${broken.length}</b><span>Requirements break</span><small>Lose direct coverage by then${broken.length ? `; ${stillMet} still met via crosswalk` : ''}.</small></div>
      </div>
    </div>
    <div>
      <div class="fam-head"><span>Family (click to open, then open a requirement to see its receipts)</span><span title="covered">Cov</span><span title="inherited">Inh</span><span title="gaps">Gap</span></div>
      ${famHtml || '<div class="notice">No gaps in this scope.</div>'}
    </div>
    <p class="muted">Covered: an adopted control with an approved mapping to the requirement and evidence that has not expired at ${esc(S.asOf)}. Inherited: not covered, but a requirement one NIST crosswalk hop away is. Open a requirement to see the receipts.</p>`;
}

function reqListHtml(reqs) {
  return reqs.map((r) => `<details class="req" data-req="${esc(r.id)}"><summary>
      <span class="rid">${esc(A.shortId(r.id))}</span><span class="rtitle">${esc(r.title)}</span>${statusPill(r.status)}</summary>
      <div class="req-body" data-status="${r.status}"></div></details>`).join('');
}

function explainHtml(reqId, status) {
  const x = A.explain(S.g, { requirement: reqId, asOf: S.asOf });
  const out = [];
  const asOf = S.asOf;
  for (const p of x.paths) {
    const bad = !p.valid && p.evidence ? [p.evidence] : [];
    const verdict = !p.evidence ? '<span class="pill fail">no evidence</span>'
      : p.valid ? `<span class="pill ok">valid until ${esc(p.expires_at)}</span>`
        : p.expires_at <= asOf ? `<span class="pill fail">expired ${esc(p.expires_at)}</span>` : '<span class="pill fail">not valid</span>';
    out.push(`<div class="receipt">${chain(p.nodes, p.rels, bad)} ${verdict}
      <span class="muted">${esc(p.control_title || '')}${p.control_owners.length ? ' · owner ' + esc(p.control_owners.map(nameOf).join(', ')) : ' · no owner'}</span>
      ${pathButton([{ nodes: p.nodes, rels: p.rels, state: p.valid ? 'ok' : 'fail', bad }])}</div>`);
  }
  for (const p of x.inherited) {
    out.push(`<div class="receipt">${chain(p.nodes, p.rels)} <span class="pill info">inherited, valid until ${esc(p.expires_at)}</span>
      <span class="muted">via ${esc(A.shortId(p.neighbour))}</span> ${pathButton([{ nodes: p.nodes, rels: p.rels, state: 'ok' }])}</div>`);
  }
  for (const p of x.proposals) {
    const nodes = [`Requirement:${reqId}`, `Proposal:${p.proposal}`, `Control:${p.control}`];
    const rels = ['TARGET<-', 'ABOUT'];
    out.push(`<div class="receipt">${chain(nodes, rels)} <span class="pill ${p.status === 'pending' ? 'warn' : p.status}">proposal ${esc(p.status)}</span>
      <span class="muted">${p.status === 'pending' ? 'proposed, not approved: does not count' : esc(p.reason || '')}</span> ${pathButton([{ nodes, rels, state: p.status === 'pending' ? 'warn' : 'fail', bad: [p.proposal] }])}</div>`);
  }
  if (!out.length) out.push(`<p class="muted">No control is mapped to this requirement${status === 'gap' ? ', and no crosswalk neighbour is covered. This is a gap.' : '.'}</p>`);
  return out.join('');
}

// ---------------------------------------------------------------------------------------------
// Head start (adopt)
// ---------------------------------------------------------------------------------------------

function renderAdopt() {
  const fw = S.adopt.framework;
  const a = A.adopt(S.g, { framework: fw, asOf: S.asOf });
  const c = A.coverage(S.g, { framework: fw, asOf: S.asOf });
  const items = a.items.map((it) => {
    const first = it.paths[0];
    const via = it.via.map((v) => `<div class="receipt">via <span class="tag">${esc(A.shortId(v.neighbour))}</span> ${v.controls.map((k) => `<span class="muted">&larr;</span> ${tag(k.control)} <span class="muted">&larr;</span> ${k.evidence.map((e) => `${tag(e.id)} <span class="muted">valid until ${esc(e.expires)}</span>`).join(', ')}`).join(' · ')}</div>`).join('');
    return `<div class="row" data-text="${esc((it.requirement + ' ' + it.title).toLowerCase())}">
      <div class="row-main"><span class="rid"><b>${esc(A.shortId(it.requirement))}</b></span><span class="grow">${esc(it.title)}</span><span class="pill info">met via crosswalk</span></div>
      <div class="row-sub">${via}${pathButton(it.paths.map((p) => ({ nodes: p.nodes, rels: p.rels, state: 'ok' })), 'Show on graph')}</div></div>`;
  }).join('');
  $('#panel-adopt').innerHTML = `
    <div class="card">
      <div class="controls">
        ${select('adopt-fw', ['800-171', 'CSF'].map((f) => [f, A.FRAMEWORK_LABEL[f]]), fw, 'Framework you are adopting')}
        <label>Filter<input type="search" id="adopt-q" placeholder="e.g. 03.13 or encryption"></label>
      </div>
      <h2 style="margin-top:1rem">${a.inheritedCount} of ${a.active} requirements are already met</h2>
      <p class="muted">Through approved mappings to NIST SP 800-53 and the official NIST crosswalk, with evidence that is still valid. You would only need to <b>adopt</b> them, not redo the work.</p>
      ${bar(c.covered, c.inherited, c.gaps, true)}
      <div class="legend-row"><span><i class="dot covered"></i>${c.covered} covered directly</span><span><i class="dot inherited"></i>${c.inherited} head start</span><span><i class="dot gap"></i>${c.gaps} still to do</span></div>
    </div>
    <div class="card"><h3>Head start list <span class="muted" id="adopt-count"></span></h3>
      <div class="rows" id="adopt-rows">${items || '<p class="muted">Nothing is inherited yet.</p>'}</div></div>
    <p class="muted">Rule: one NIST crosswalk hop, either direction. A requirement that is covered directly is not listed here.</p>`;
}

// ---------------------------------------------------------------------------------------------
// What breaks
// ---------------------------------------------------------------------------------------------

function blastUntil() {
  const w = S.blast.window;
  if (/^\d+$/.test(w)) return { until: A.addDays(S.asOf, Number(w)), label: `the next ${w} days` };
  if (w === 'custom') {
    const d = S.blast.custom;
    if (/^\d{4}-\d{2}-\d{2}$/.test(d) && d > S.asOf) return { until: d, label: d };
    return { until: A.addDays(S.asOf, 30), label: 'the next 30 days (pick a later date)' };
  }
  const a = S.meta.audits.find((x) => x.id === w);
  return { until: a.date, label: `${a.id} on ${a.date}` };
}

function renderBlast() {
  const { until, label } = blastUntil();
  const b = A.blast(S.g, { asOf: S.asOf, until });
  const ownerRisk = A.ownerRisk(S.g, { asOf: S.asOf });
  const evTitles = S.names;
  const winOpts = [['30', 'Next 30 days'], ['60', 'Next 60 days'], ['90', 'Next 90 days'],
    ...S.meta.audits.map((a) => [a.id, `Before ${a.id} (${a.date})`]), ['custom', 'Pick a date…']];

  const expiring = b.expiring.map((e) => `<div class="row">
      <div class="row-main"><span class="tag">${esc(e.evidence)}</span><span class="grow">${esc(evTitles[e.evidence] || '')}</span><span class="pill warn">expires ${esc(e.expires_at)}</span></div>
      <div class="row-sub">proves ${e.proves.map((c) => tag(c)).join(' ') || 'nothing'}${e.controls_left_without_valid_evidence.length ? ` &middot; leaves <b>${plural(e.controls_left_without_valid_evidence.length, 'control')}</b> without valid evidence` : ''}${e.controls_with_replacement.length ? ` &middot; ${plural(e.controls_with_replacement.length, 'control')} have a replacement` : ''}${e.requested_by.length ? ` &middot; requested by ${esc(e.requested_by.join(', '))}` : ''}</div></div>`).join('');

  const brokenFw = A.FRAMEWORKS.map((fw) => {
    const list = b.byFramework[fw];
    if (!list.length) return '';
    const rows = list.map((r) => {
      const state = r.still_inherited ? 'warn' : 'fail';
      const paths = [...r.paths.map((p) => ({ ...p, state: 'fail', bad: r.evidence_lost })), ...r.inherited_paths.map((p) => ({ ...p, state: 'ok' }))];
      return `<div class="row"><div class="row-main"><b>${esc(A.shortId(r.requirement))}</b><span class="grow">${esc(r.title)}</span>
        <span class="pill ${state}">${r.still_inherited ? 'still met via crosswalk' : 'fully broken'}</span></div>
        <div class="row-sub">loses ${r.controls_lost.map((c) => tag(c)).join(' ')} (evidence ${r.evidence_lost.map((e) => tag(e, 'warn')).join(' ')})${r.still_inherited ? ` &middot; still held up through ${r.inherited_via.map((v) => tag(v)).join(' ')}` : ''} ${pathButton(paths, 'Show path')}</div></div>`;
    }).join('');
    return `<h3 style="margin-top:.8rem">${esc(A.FRAMEWORK_LABEL[fw])} <span class="muted">(${list.length})</span></h3><div class="rows">${rows}</div>`;
  }).join('');

  const audits = b.audits.map((a) => `<div class="row"><div class="row-main"><b>${esc(a.audit)}</b><span class="grow">${esc(a.name)}</span><span class="muted">${esc(a.date)}</span></div>
      <div class="row-sub">${a.requests_expiring_evidence.length ? `requests ${a.requests_expiring_evidence.map((e) => tag(e, 'warn')).join(' ')}` : ''}${a.requests_expiring_evidence.length && a.broken_requirements_in_framework ? ' &middot; ' : ''}${a.broken_requirements_in_framework ? `${plural(a.broken_requirements_in_framework, 'requirement')} in its framework break` : ''}</div></div>`).join('');

  const total = b.broken.length;
  const notInh = b.brokenNotInherited.length;
  const people = Object.values(ownerRisk.people);
  const pid = people.some((p) => p.id === S.blast.person) ? S.blast.person : (ownerRisk.ranking[0] || people[0] || {}).id;
  const p = ownerRisk.people[pid];
  const personOpts = people.map((x) => [x.id, `${x.name} (${x.controls.length} sole-owned)`]);
  const ownerHtml = p ? `
      ${select('blast-person', personOpts, pid, 'Person')}
      <p style="margin-top:.8rem"><b>${esc(p.name)}</b> is the only owner of <b>${plural(p.controls.length, 'control')}</b>${p.highSystems.length ? `, touching ${plural(p.highSystems.length, 'high-criticality system')}` : ''}.
        ${p.dependent.length ? `<b>${plural(p.dependent.length, 'requirement')}</b> rely on her controls alone${p.audits.length ? `, affecting ${esc(p.audits.join(', '))}` : ''}.` : 'No requirement relies on her controls alone.'}</p>
      <div class="receipt">${p.controls.map((c) => tag(c)).join(' ') || '<span class="muted">no sole-owned controls</span>'}</div>
      ${p.dependent.length ? `<div class="row-sub">Requirements: ${p.dependent.slice(0, 24).map((d) => tag(d.requirement)).join(' ')}${p.dependent.length > 24 ? ` +${p.dependent.length - 24} more` : ''} ${pathButton(p.dependent.slice(0, 6).flatMap((d) => d.paths.slice(0, 1)).map((x) => ({ ...x, state: 'warn' })), 'Show on graph')}</div>` : ''}
      <p style="margin-top:.6rem"><button type="button" class="btn small" data-act="whatif-remove" data-person="${esc(pid)}">What if ${esc(p.name.split(' ')[0])} leaves?</button></p>` : '<p class="muted">No people in the graph.</p>';

  const topReuse = A.reuse(S.g, { asOf: S.asOf, top: 5 });
  const removed = S.whatIf.filter((w) => w.kind === 'remove').map((w) => `
    <div class="card" style="border-color:var(--warn)"><h2>If ${esc(w.name)} leaves</h2>
      <p><b>${plural(w.controls.length, 'control')}</b> ${w.controls.length === 1 ? 'is' : 'are'} left with no owner${w.dependent.length ? `, and <b>${plural(w.dependent.length, 'requirement')}</b> depend on ${w.controls.length === 1 ? 'it' : 'them'} alone${w.audits.length ? ` (${esc(w.audits.join(', '))})` : ''}` : ''}.</p>
      <div class="receipt">${w.controls.map((c) => tag(c, 'warn')).join(' ')}</div>
      ${w.dependent.length ? `<div class="row-sub">Requirements: ${w.dependent.slice(0, 24).map((d) => tag(d.requirement)).join(' ')}${w.dependent.length > 24 ? ` +${w.dependent.length - 24} more` : ''}</div>` : ''}</div>`).join('');
  $('#panel-blast').innerHTML = `${removed}
    <div class="card">
      <div class="controls">
        ${select('blast-window', winOpts, S.blast.window, 'Window')}
        <label id="blast-custom-wrap"${S.blast.window === 'custom' ? '' : ' hidden'}>Date<input type="date" id="blast-custom" min="${esc(A.addDays(S.asOf, 1))}" value="${esc(S.blast.custom)}"></label>
      </div>
      <h2 style="margin-top:1rem">${plural(b.expiring.length, 'evidence item')} expire${b.expiring.length === 1 ? 's' : ''} in ${esc(label)}</h2>
      <p>${total ? `<b>${plural(total, 'requirement')}</b> lose direct coverage (${total - notInh} still met through the crosswalk, <b>${notInh}</b> fully broken).` : 'No requirement loses direct coverage.'}
        ${b.controlsLeft.length ? ` ${plural(b.controlsLeft.length, 'control')} would have no valid evidence left.` : ''}</p>
      <div class="stats">${A.FRAMEWORKS.map((fw) => `<div class="stat"><b>${b.counts[fw]}</b><span>${esc(A.FRAMEWORK_LABEL[fw])}</span><small>requirements lose direct coverage</small></div>`).join('')}
        <div class="stat"><b>${b.audits.length}</b><span>${b.audits.length === 1 ? 'Audit affected' : 'Audits affected'}</span><small>Audits that ask for expiring evidence or lose a requirement.</small></div></div>
    </div>
    <div class="grid2">
      <div class="card"><h2>Evidence about to expire</h2><div class="rows">${expiring || '<p class="muted">Nothing expires in this window.</p>'}</div></div>
      <div class="card"><h2>Audits affected</h2><div class="rows">${audits || '<p class="muted">No audit is affected.</p>'}</div>
        <p class="muted" style="margin-top:.6rem">An audit is affected if it requests an expiring item, or its framework has a requirement that breaks.</p></div>
    </div>
    <div class="card"><h2>Requirements that break</h2>${brokenFw || '<p class="muted">Nothing breaks.</p>'}</div>
    <div class="grid2">
      <div class="card"><h2>Owner risk: what if someone leaves?</h2>${ownerHtml}
        <p class="muted" style="margin-top:.6rem">Controls with no owner today: ${ownerRisk.unowned.map((u) => tag(u.control, 'warn')).join(' ') || 'none'}.</p></div>
      <div class="card"><h2>Evidence that earns the most credit</h2>
        <div class="rows">${topReuse.map((r) => `<div class="row"><div class="row-main"><span class="tag">${esc(r.evidence)}</span><span class="grow">${esc(evTitles[r.evidence] || '')}</span></div>
          <div class="row-sub">${plural(r.direct_count, 'requirement')} directly, ${plural(r.reach_count, 'requirement')} with one crosswalk hop, across ${plural(r.framework_count, 'framework')}; expires ${esc(r.expires_at)}</div></div>`).join('')}</div></div>
    </div>`;
}

// ---------------------------------------------------------------------------------------------
// Graph
// ---------------------------------------------------------------------------------------------

function renderGraph() {
  if (!S.graphView) {
    S.graphView = new GraphView($('#cy'), S.g, { onSelect: showNodeInfo });
    $('#graph-legend').innerHTML = LEGEND.map((l) => `<li><svg viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="5.5" fill="${l.color}"></circle></svg>${l.label}</li>`).join('');
    showNodeInfo(null);
  }
  if (S.graphStale) {
    S.graphStale = false;
    S.graphView.clear();
    S.graphView.select('Requirement:800-171:03.05.03');
  }
  requestAnimationFrame(() => S.graphView.resize());
}

function showNodeInfo(d, info) {
  const el = $('#graph-info');
  if (!d) {
    el.innerHTML = '<h3>Nothing selected</h3><p class="muted">Click a node to see its properties and pull in its neighbours. Search above to start from any requirement, control, evidence item or person.</p>';
    return;
  }
  const rows = Object.entries(d.props).filter(([k]) => k !== 'id').sort(([a], [b]) => A.nat(a, b));
  const extra = d.label === 'Evidence'
    ? (d.props.expires_at <= S.asOf ? '<span class="pill fail">expired</span>' : '<span class="pill ok">valid</span>')
    : d.label === 'Proposal' ? `<span class="pill ${d.props.status === 'pending' ? 'warn' : d.props.status}">${esc(d.props.status)}</span>` : '';
  const more = info && info.total > info.shown ? `<p class="muted">Showing ${info.shown} of ${info.total} neighbours.</p>` : '';
  el.innerHTML = `<h3>${esc(d.label)} ${extra}</h3><p class="mono" style="overflow-wrap:anywhere">${esc(d.id)}</p>
    <dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(Array.isArray(v) ? v.join(', ') : v)}</dd>`).join('')}</dl>${more}`;
}

function graphSearch(q) {
  q = q.trim().toLowerCase();
  const box = $('#graph-results');
  if (!q) { box.hidden = true; return; }
  const rows = S.g.run(`MATCH (n) WHERE NOT n:Meta AND (toLower(n.id) CONTAINS $q OR toLower(coalesce(n.title, n.name, '')) CONTAINS $q)
      RETURN labels(n)[0] AS label, n.id AS id, coalesce(n.title, n.name, '') AS title LIMIT 15`, { q }).rows;
  box.hidden = false;
  box.innerHTML = rows.length
    ? rows.map((r) => `<li><button type="button" data-act="graph-pick" data-ref="${esc(r.label + ':' + r.id)}"><b>${esc(A.shortId(r.id))}</b> <span class="muted">${esc(r.label)}</span> ${esc(r.title).slice(0, 80)}</button></li>`).join('')
    : '<li class="muted" style="padding:.4rem .6rem">No match</li>';
}

function goPaths(paths) {
  showTab('graph');
  S.graphStale = false;
  S.graphView.showPaths(paths);
  $('#panel-graph').scrollIntoView({ block: 'start', behavior: 'smooth' });
  showNodeInfo(null);
}

// ---------------------------------------------------------------------------------------------
// Agent log
// ---------------------------------------------------------------------------------------------

function verdictOf(res) {
  if (!res.exists) return 'fail';
  if (res.valid) return 'ok';
  return res.problems.length && res.problems.every((p) => /proposed/i.test(p)) ? 'warn' : 'fail';
}

function liveCatchHtml() {
  const rec = S.liveCatch;
  if (!rec) return '<div class="card"><h2>Live catch</h2><p class="muted">No recorded answer was exported.</p></div>';
  const t0 = performance.now();
  const checked = rec.paths.map((p) => ({ p, res: A.checkPath(S.g, { nodes: p.nodes, rels: p.rels, asOf: S.asOf }) }));
  const ms = performance.now() - t0;
  const byId = Object.fromEntries(checked.map((c) => [c.p.id, c]));
  const symbol = { fail: '&#x2716;', warn: '&#x26A0;', ok: '&#x2714;' };
  const word = { fail: 'Failed', warn: 'Pending approval', ok: 'Verified' };
  const claims = rec.claims.map((cl) => {
    const cs = cl.path_ids.map((id) => byId[id]).filter(Boolean);
    const v = cs.some((c) => verdictOf(c.res) === 'fail') ? 'fail' : cs.some((c) => verdictOf(c.res) === 'warn') ? 'warn' : 'ok';
    const detail = cs.map((c) => {
      const cv = verdictOf(c.res);
      const bad = [...c.res.problems.join(' ').matchAll(/(?:Evidence:|\()?(EV-\d+|PR-\d+)/g)].map((m) => m[1]);
      return `<div class="receipt">${chain(c.p.nodes, c.p.rels, bad)} <span class="mono muted">${esc(c.p.id)}</span></div>
        <div class="verdict ${cv}">${symbol[cv]} ${esc(c.res.problems.join('; ') || (c.res.valid ? 'path exists and is valid' : 'path not found'))}
        &nbsp; ${pathButton([{ nodes: c.p.nodes, rels: c.p.rels, state: cv === 'ok' ? 'ok' : cv, bad }], 'Show broken path on graph')}</div>`;
    }).join('');
    return `<div class="claim ${v}"><div><span class="verdict ${v}">${symbol[v]} ${word[v]}</span> &mdash; ${esc(cl.text)}</div>${detail}</div>`;
  }).join('');

  // the corrected answer, built from what the checks found
  const actions = [];
  const allProblems = checked.flatMap((c) => c.res.problems);
  for (const m of allProblems.join(' | ').matchAll(/Evidence:(EV-\d+) expired (\d{4}-\d{2}-\d{2})/g)) {
    const owner = S.g.run('MATCH (p:Person)-[:OWNS]->(e:Evidence {id: $id}) RETURN p.name AS n', { id: m[1] }).rows[0];
    actions.push(`renew <b>${esc(m[1])}</b> (expired ${esc(m[2])}${owner ? ', owner ' + esc(owner.n) : ''})`);
  }
  for (const m of allProblems.join(' | ').matchAll(/mapping (\S+) -> (\S+) is proposed \((PR-\d+)\)/g)) {
    actions.push(`review proposal <b>${esc(m[3])}</b> (${esc(m[1])} &rarr; ${esc(A.shortId(m[2]))})`);
  }
  const allOk = checked.every((c) => c.res.valid);
  const fixed = allOk
    ? '<b>Confirmed.</b> Every cited path still holds at the demo date.'
    : `<b>Not covered.</b> ${actions.length ? actions.map((a, i) => (i === 0 ? a.charAt(0).toUpperCase() + a.slice(1) : a)).join(', then ') + '.' : 'At least one cited path no longer holds.'}`;

  return `<div class="card">
      <h2>The live catch</h2>
      <p class="muted">A recorded agent answer, re-checked against the live graph. The agent works from the old spreadsheet; the graph does not.</p>
      <p><b>${esc(S.names[rec.asked_by] || rec.asked_by)} asks:</b> ${esc(rec.question)}</p>
      <div class="quote"><b style="font-style:normal">${esc(rec.agent)}</b>: ${esc(rec.answer_text)}</div>
      <h3>Claim check <span class="muted" style="font-weight:400">&mdash; ${plural(rec.paths.length, 'cited path')} re-run in ${ms.toFixed(0)} ms, in your browser</span></h3>
      <div style="margin-top:.5rem">${claims}</div>
      <div class="fixed"><b>Corrected answer.</b> ${fixed}</div>
    </div>`;
}

function renderAgent() {
  const props = A.proposals(S.g);
  const decs = Object.fromEntries(A.decisions(S.g).map((d) => [d.proposal, d]));
  const rIds = [...new Set(props.map((p) => p.requirement))];
  const rTitle = Object.fromEntries(S.g.run('MATCH (r:Requirement) WHERE r.id IN $ids RETURN r.id AS id, r.title AS t', { ids: rIds }).rows.map((r) => [r.id, r.t]));
  const order = { pending: 0, approved: 1, rejected: 2 };
  props.sort((a, b) => (order[a.status] - order[b.status]) || A.nat(a.proposal, b.proposal));
  const count = (s) => props.filter((p) => p.status === s).length;
  const agents = [...new Set(props.map((p) => p.by))];
  const rows = props.map((p) => {
    const d = decs[p.proposal];
    const state = p.status === 'pending' ? 'warn' : p.status === 'approved' ? 'ok' : 'fail';
    return `<div class="row">
      <div class="row-main"><span class="tag">${esc(p.proposal)}</span><span class="pill ${p.status}">${esc(p.status)}</span>
        <span class="grow">${tag(p.control)} <span class="muted">&rarr;</span> ${tag(p.requirement)} <span class="muted">${esc(rTitle[p.requirement] || '')}</span></span></div>
      <div class="row-sub"><b>${esc(p.by || 'agent')}</b>: ${esc(p.rationale)}</div>
      <div class="row-sub">${d ? `Decision: <b>${esc(d.outcome)}</b> by ${esc(S.names[d.by] || d.by)} on ${esc(d.at)}${d.reason ? ' &mdash; &ldquo;' + esc(d.reason) + '&rdquo;' : ''}` : 'Awaiting a human decision. A pending proposal never counts as coverage.'}
        ${pathButton([{ nodes: p.nodes, rels: p.rels, state, bad: [p.proposal] }], 'Show on graph')}</div></div>`;
  }).join('');
  $('#panel-agent').innerHTML = `${liveCatchHtml()}
    <div class="card"><h2>Proposals and decisions</h2>
      <p class="muted">Agents can only <em>propose</em>. A person approves or rejects, and the decision is stored in the same graph, so the next agent reads it before suggesting again.
      ${plural(props.length, 'proposal')} by ${esc(agents.join(', ') || 'no agent')}: ${count('approved')} approved, ${count('rejected')} rejected, ${count('pending')} pending.</p>
      <div class="rows">${rows || '<p class="muted">No proposals in the graph.</p>'}</div></div>`;
}

// ---------------------------------------------------------------------------------------------
// Scorecard
// ---------------------------------------------------------------------------------------------

async function renderScorecardTab() {
  const panel = $('#panel-scorecard');
  if (S.scorecard === undefined) {
    panel.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    S.scorecard = S.meta.has_scorecard ? await getJsonOrNull('data/scorecard.json') : null;
  }
  panel.innerHTML = `<div class="card accent"><h2>Headline result: 45% to 95%</h2>
      <p>Same Claude model, same 20 questions (14 planted traps). Reading the spreadsheet: <b>9/20 right (45%)</b>, fell for 6 of 14 traps. With the Relate graph and claim checker: <b>19/20 right (95%)</b>, 0 of 14 traps, <b>0 wrong claims shown</b>, <b>109/109 claims</b> backed by a valid receipt. The one miss (GQ-11) was an incomplete answer, not a false claim.</p>
      <p class="muted">The detail is below. <a href="index.html#result">Read the short version on the overview page.</a></p></div>${renderScorecard(S.scorecard)}`;
}

// ---------------------------------------------------------------------------------------------
// what-if
// ---------------------------------------------------------------------------------------------

function openExpire() {
  const sole = new Map(S.g.run(
    `MATCH (e:Evidence)-[:PROVES]->(c:Control {adopted: true})
     WHERE e.expires_at > date($as_of)
       AND NOT EXISTS { MATCH (c)<-[:PROVES]-(o:Evidence) WHERE o.id <> e.id AND o.expires_at > date($as_of) }
     RETURN e.id AS id, count(c) AS n`, { as_of: S.asOf }).rows.map((r) => [r.id, r.n]));
  // evidence that is the ONLY proof of some control first (expiring it visibly drops coverage), then by reach
  const ev = A.reuse(S.g, { asOf: S.asOf }).sort((a, b) => (sole.get(b.evidence) || 0) - (sole.get(a.evidence) || 0) || a.rank - b.rank);
  $('#sel-expire').innerHTML = ev.map((r) => {
    const n = sole.get(r.evidence) || 0;
    const note = n ? `only proof of ${plural(n, 'control')}` : 'has back-up evidence';
    return `<option value="${esc(r.evidence)}">${esc(r.evidence)} · ${esc((S.names[r.evidence] || '').slice(0, 48))} · ${note}, reaches ${r.reach_count}</option>`;
  }).join('');
  $('#dlg-expire').showModal();
}

function openRemove(preselect) {
  const risk = A.ownerRisk(S.g, { asOf: S.asOf });
  const people = Object.values(risk.people).sort((a, b) => b.controls.length - a.controls.length || A.nat(a.id, b.id));
  $('#sel-remove').innerHTML = people.map((p) => `<option value="${esc(p.id)}"${p.id === preselect ? ' selected' : ''}>${esc(p.name)} · solely owns ${p.controls.length}</option>`).join('');
  $('#dlg-remove').showModal();
}

function doExpire(id) {
  const d = A.addDays(S.asOf, -1);
  S.g.run('MATCH (e:Evidence {id: $id}) SET e.expires_at = date($d)', { id, d });
  S.whatIf.push({ text: `${id} expired (${d})` });
  invalidate();
}

function doRemove(id) {
  const name = S.names[id] || id;
  const p = A.ownerRisk(S.g, { asOf: S.asOf }).people[id];  // what they owned, read before the delete
  S.g.run('MATCH (p:Person {id: $id}) DETACH DELETE p', { id });
  S.whatIf.push({ kind: 'remove', text: `${name} removed`, name, controls: p ? p.controls : [], dependent: p ? p.dependent : [], audits: p ? p.audits : [] });
  invalidate();
  showTab('blast');
}

function doReset() {
  S.g.load();
  S.whatIf = [];
  invalidate();
}

// ---------------------------------------------------------------------------------------------
// events
// ---------------------------------------------------------------------------------------------

function wire() {
  $('#tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-tab]');
    if (b) showTab(b.dataset.tab);
  });
  $('#tabs').addEventListener('keydown', (e) => {
    const i = TABS.indexOf(S.tab);
    const next = e.key === 'ArrowRight' ? (i + 1) % TABS.length : e.key === 'ArrowLeft' ? (i + TABS.length - 1) % TABS.length : -1;
    if (next >= 0) { showTab(TABS[next]); $('#tab-' + TABS[next]).focus(); e.preventDefault(); }
  });
  document.querySelectorAll('[data-tab-link]').forEach((el) => el.addEventListener('click', (e) => { e.preventDefault(); showTab(el.dataset.tabLink); $('#panel-' + el.dataset.tabLink).scrollIntoView({ behavior: 'smooth', block: 'start' }); }));
  document.querySelectorAll('[data-start]').forEach((el) => el.addEventListener('click', () => {
    const what = el.dataset.start;
    if (what === 'receipts') {
      S.cov = { framework: '800-171', audit: '', gapsOnly: false, expandAll: false };
      S.rendered.coverage = -1;
      showTab('coverage');
      const fam = document.querySelector('#panel-coverage .fam[data-fam="800-171:03.05"]');
      if (fam) { fam.open = true; fam.scrollIntoView({ behavior: 'smooth', block: 'center' }); setTimeout(() => { const rq = document.querySelector('#panel-coverage .req[data-req="800-171:03.05.03"]'); if (rq) rq.open = true; }, 60); }
    } else if (what === 'catch') {
      showTab('agent');
      $('#panel-agent').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else if (what === 'expire') openExpire();
  }));
  const hideStart = () => { $('#start').hidden = true; try { localStorage.setItem('cw-start-hidden', '1'); } catch { /* storage may be blocked */ } };
  $('#start-hide').addEventListener('click', hideStart);
  try { if (localStorage.getItem('cw-start-hidden') === '1') $('#start').hidden = true; } catch { /* storage may be blocked */ }
  $('#btn-expire').addEventListener('click', openExpire);
  $('#btn-remove').addEventListener('click', () => openRemove());
  $('#btn-reset').addEventListener('click', doReset);
  $('#dlg-expire').addEventListener('close', (e) => { if (e.target.returnValue === 'ok') doExpire($('#sel-expire').value); });
  $('#dlg-remove').addEventListener('close', (e) => { if (e.target.returnValue === 'ok') doRemove($('#sel-remove').value); });

  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-act]');
    if (!el) {
      if (!e.target.closest('#graph-search, #graph-results')) $('#graph-results').hidden = true;
      return;
    }
    const act = el.dataset.act;
    if (act === 'show-paths') goPaths(JSON.parse(el.dataset.paths));
    else if (act === 'reset') doReset();
    else if (act === 'toggle-expand') { S.cov.expandAll = !S.cov.expandAll; S.rendered.coverage = -1; renderTab('coverage'); }
    else if (act === 'whatif-remove') openRemove(el.dataset.person);
    else if (act === 'graph-pick') {
      $('#graph-results').hidden = true;
      S.graphView.clear();
      S.graphView.select(el.dataset.ref);
    }
  });

  // lazy fill of family and requirement bodies
  $('#panel-coverage').addEventListener('toggle', (e) => {
    const d = e.target;
    if (!d.open) return;
    if (d.classList.contains('fam')) {
      const box = d.querySelector('.reqs');
      if (box.dataset.filled) return;
      const fam = S.famIndex.get(d.dataset.fam);
      box.innerHTML = reqListHtml(S.cov.gapsOnly ? fam.reqs.filter((r) => r.status === 'gap') : fam.reqs);
      box.dataset.filled = '1';
    } else if (d.classList.contains('req')) {
      const body = d.querySelector('.req-body');
      if (body.dataset.filled) return;
      body.innerHTML = explainHtml(d.dataset.req, body.dataset.status);
      body.dataset.filled = '1';
    }
  }, true);

  // change handlers for the controls rendered inside panels
  document.addEventListener('change', (e) => {
    const id = e.target.id;
    if (id === 'cov-fw') { S.cov.framework = e.target.value; S.cov.audit = ''; rerender('coverage'); }
    else if (id === 'cov-audit') {
      S.cov.audit = e.target.value;
      if (S.cov.audit) S.cov.framework = S.meta.audits.find((a) => a.id === S.cov.audit).framework;
      rerender('coverage');
    } else if (id === 'cov-gaps') { S.cov.gapsOnly = e.target.checked; rerender('coverage'); }
    else if (id === 'adopt-fw') { S.adopt.framework = e.target.value; rerender('adopt'); }
    else if (id === 'blast-window') { S.blast.window = e.target.value; rerender('blast'); }
    else if (id === 'blast-custom') { S.blast.custom = e.target.value; rerender('blast'); }
    else if (id === 'blast-person') { S.blast.person = e.target.value; rerender('blast'); }
  });
  document.addEventListener('input', (e) => {
    if (e.target.id === 'adopt-q') {
      const q = e.target.value.trim().toLowerCase();
      let n = 0;
      for (const row of document.querySelectorAll('#adopt-rows .row')) {
        const hit = !q || row.dataset.text.includes(q);
        row.hidden = !hit;
        if (hit) n++;
      }
      $('#adopt-count').textContent = q ? `(${n} shown)` : '';
    }
  });
  $('#graph-search').addEventListener('submit', (e) => { e.preventDefault(); graphSearch($('#graph-q').value); });
  $('#graph-q').addEventListener('input', (e) => graphSearch(e.target.value));
  $('#graph-clear').addEventListener('click', () => { $('#graph-q').value = ''; $('#graph-results').hidden = true; S.graphView.clear(); showNodeInfo(null); });
  window.addEventListener('hashchange', () => {
    const h = location.hash.slice(1);
    if (TABS.includes(h) && h !== S.tab) showTab(h, { push: false });
  });
  window.addEventListener('resize', () => refreshChromeHeight());
}

function refreshChromeHeight() {
  document.documentElement.style.setProperty('--top-h', $('.top').offsetHeight + 'px');
}

function rerender(tab) {
  const keep = document.activeElement && document.activeElement.id;
  S.rendered[tab] = -1;
  renderTab(tab);
  if (keep) document.getElementById(keep)?.focus();
}

boot();
