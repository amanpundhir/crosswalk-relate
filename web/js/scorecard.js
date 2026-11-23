// Scorecard tab: renders data/scorecard.json (written by `crosswalk scorecard`, copied by export_web).
// The file's shape is not fixed here, so this renders any JSON generically: scalars as text, arrays of
// objects as tables, objects as nested sections, with pass/fail-looking values shown as pills.

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const label = (k) => String(k).replace(/_/g, ' ').replace(/\b(\w)/, (m) => m.toUpperCase());

function scalar(v, key = '') {
  if (v === null || v === undefined) return '<span class="muted">n/a</span>';
  if (typeof v === 'boolean') return `<span class="pill ${v ? 'ok' : 'fail'}">${v ? 'pass' : 'fail'}</span>`;
  if (typeof v === 'string' && /^(pass|passed|ok|met)$/i.test(v)) return `<span class="pill ok">${esc(v)}</span>`;
  if (typeof v === 'string' && /^(fail|failed|missed|not met)$/i.test(v)) return `<span class="pill fail">${esc(v)}</span>`;
  if (typeof v === 'number' && /(rate|ratio|precision|recall|accuracy|pct|percent)/i.test(key) && v <= 1) {
    return `${(v * 100).toFixed(1)}%`;
  }
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/\.?0+$/, '');
  return esc(v);
}

function table(rows) {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const head = cols.map((c) => `<th>${esc(label(c))}</th>`).join('');
  const body = rows.map((r) => `<tr>${cols.map((c) => `<td>${cell(r[c], c)}</td>`).join('')}</tr>`).join('');
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function cell(v, key) {
  if (Array.isArray(v)) return v.every((x) => typeof x !== 'object') ? esc(v.join(', ')) : `<code>${esc(JSON.stringify(v))}</code>`;
  if (v && typeof v === 'object') return `<code>${esc(JSON.stringify(v))}</code>`;
  return scalar(v, key);
}

function node(v, key, depth) {
  if (Array.isArray(v)) {
    if (v.length && v.every((x) => x && typeof x === 'object' && !Array.isArray(x))) return table(v);
    return `<p>${v.map((x) => scalar(x, key)).join(', ') || '<span class="muted">none</span>'}</p>`;
  }
  if (v && typeof v === 'object') {
    const scalars = Object.entries(v).filter(([, x]) => x === null || typeof x !== 'object');
    const nested = Object.entries(v).filter(([, x]) => x !== null && typeof x === 'object');
    let out = '';
    if (scalars.length) {
      out += `<dl class="kv">${scalars.map(([k, x]) => `<dt>${esc(label(k))}</dt><dd>${scalar(x, k)}</dd>`).join('')}</dl>`;
    }
    for (const [k, x] of nested) {
      out += `<div class="${depth < 1 ? 'card' : ''}"><h3>${esc(label(k))}</h3>${node(x, k, depth + 1)}</div>`;
    }
    return out;
  }
  return `<p>${scalar(v, key)}</p>`;
}

const STATUS = { pass: 'ok', miss: 'fail', info: 'info' };
const val = (v) => (typeof v === 'boolean' ? (v ? 'yes' : 'no') : esc(v));
const pill = (st) => `<span class="pill ${STATUS[st] || 'info'}">${esc(st)}</span>`;

// The shape written by `crosswalk scorecard`: headline[], summary, sections[{id,title,metrics[]}], timings, agent_run_history.
function renderStructured(d) {
  const headline = `<div class="card"><h3>Headline</h3><div class="table-wrap"><table><thead><tr><th>Metric</th><th>Result</th><th>Note</th></tr></thead><tbody>${
    d.headline.map((h) => `<tr><td>${esc(h.row)}</td><td><strong>${esc(h.value)}</strong></td><td class="muted">${esc(h.note)}</td></tr>`).join('')}</tbody></table></div>
    <p class="muted">${esc(d.note)}</p></div>`;
  const s = d.summary || {};
  const summary = `<p>${pill('pass')} ${s.pass ?? 0} &nbsp; ${pill('miss')} ${s.miss ?? 0} &nbsp; ${pill('info')} ${s.info ?? 0}
    <span class="muted">&nbsp;demo date ${esc(d.as_of)}, ${esc(d.mode)} run${(s.misses || []).length ? `, missed: ${esc(s.misses.join(', '))}` : ''}</span></p>`;
  const sections = d.sections.map((sec) => `<div class="card"><h3>${esc(sec.title)}</h3><div class="table-wrap"><table>
    <thead><tr><th>ID</th><th>Metric</th><th>Value</th><th>Target</th><th>Status</th><th>Source</th></tr></thead><tbody>${
    sec.metrics.map((m) => `<tr><td>${esc(m.id)}</td><td>${esc(m.name)}${m.note ? `<br><span class="muted">${esc(m.note)}</span>` : ''}</td>
      <td>${val(m.value)}</td><td>${esc(m.target)}</td><td>${pill(m.status)}</td><td class="muted">${esc(m.source)}</td></tr>`).join('')}</tbody></table></div></div>`).join('');
  const h = d.agent_run_history;
  const n = (v) => (v === null || v === undefined ? 'n/a' : v);
  const history = h && h.run1 ? `<div class="card"><h3>Agent run history</h3><p class="muted">${esc(h.note)} (${esc(h.label)})</p><div class="table-wrap"><table>
    <thead><tr><th>Setup</th><th>Run 1 accuracy</th><th>Run 1 wrong claims / answers</th><th>Run 2 accuracy</th><th>Run 2 wrong claims / answers</th></tr></thead><tbody>${
    [['A', 'Spreadsheet'], ['B', 'Graph'], ['C', 'Graph + checker']].map(([k, name]) => `<tr><td>${name}</td>
      <td>${(h.run1[k].accuracy * 100).toFixed(0)}%</td><td>${n(h.run1[k].wrong_claims_shown)} / ${h.run1[k].wrong_answers_shown}</td>
      <td>${(h.run2[k].accuracy * 100).toFixed(0)}%</td><td>${n(h.run2[k].wrong_claims_shown)} / ${h.run2[k].wrong_answers_shown}</td></tr>`).join('')}</tbody></table></div></div>` : '';
  const t = d.timings || {};
  const ql = t.query_latency || {};
  const timings = `<div class="card"><h3>Timings (machine dependent)</h3><div class="table-wrap"><table><thead><tr><th>Query</th><th>p50 ms</th><th>p95 ms</th></tr></thead><tbody>${
    Object.entries(ql).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.p50_ms}</td><td>${v.p95_ms}</td></tr>`).join('')}</tbody></table></div>
    <dl class="kv">${Object.entries(t).filter(([k, v]) => k !== 'query_latency' && typeof v !== 'object').map(([k, v]) => `<dt>${esc(label(k))}</dt><dd>${esc(v)}</dd>`).join('')}</dl></div>`;
  return `<div class="card"><h2>${esc(d.title)}</h2>${summary}</div>${headline}${sections}${history}${timings}`;
}

export function renderScorecard(data) {
  if (!data) {
    return `<div class="card"><h2>Scorecard</h2>
      <p>The scorecard isn't included in this copy.</p>
      <p class="muted">Run <code>crosswalk scorecard</code> (it writes <code>eval/scorecard.json</code>), then
      <code>python -m crosswalk.export_web</code> to copy it here. The scorecard needs no AI key.</p></div>`;
  }
  if (Array.isArray(data.sections) && Array.isArray(data.headline)) return renderStructured(data);
  return `<div class="card"><h2>Scorecard</h2><p class="muted">Read from <code>data/scorecard.json</code>, generated by <code>crosswalk scorecard</code>.</p></div>${node(data, '', 0)}`;
}
