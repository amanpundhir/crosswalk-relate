// The core Crosswalk questions over a GraphDb. A JavaScript port of the reshaping done by
// src/crosswalk/queries.py and coverage.py; ALL graph logic stays in queries/*.cypher (unchanged text).

const collator = new Intl.Collator('en', { numeric: true, sensitivity: 'base' });
export const nat = (a, b) => collator.compare(String(a), String(b));
export const natSorted = (xs) => [...xs].sort(nat);

export const FRAMEWORKS = ['800-53', '800-171', 'CSF'];
export const FRAMEWORK_LABEL = { '800-53': 'NIST SP 800-53', '800-171': 'NIST SP 800-171', CSF: 'NIST CSF 2.0' };

const DAY = 86400000;
export function addDays(iso, days) {
  const d = new Date(iso + 'T00:00:00Z');
  return new Date(d.getTime() + days * DAY).toISOString().slice(0, 10);
}
export function daysBetween(a, b) {
  return Math.round((new Date(b + 'T00:00:00Z') - new Date(a + 'T00:00:00Z')) / DAY);
}

export function readAsOf(g) {
  return g.run('MATCH (m:Meta) RETURN toString(m.as_of) AS as_of').rows[0].as_of;
}

// ---- Q1 coverage ---------------------------------------------------------------------------------

/** Per-requirement status with totals; an audit narrows to its framework (and baseline). */
export function coverage(g, { framework, audit = null, asOf }) {
  let baseline = null;
  if (audit) {
    const a = g.run(
      'MATCH (a:Audit {id: $id})-[:SCOPES]->(f:Framework) RETURN f.id AS framework, a.scope_baseline AS baseline',
      { id: audit },
    ).rows[0];
    framework = a.framework;
    baseline = a.baseline || null;
  }
  const row = g.q('q1_coverage', { framework, as_of: asOf })[0];
  let reqs = row.requirements;
  if (baseline) {
    const keep = new Set(
      g.run('MATCH (r:Requirement) WHERE $b IN r.baselines RETURN r.id AS id', { b: baseline }).rows.map((r) => r.id),
    );
    reqs = reqs.filter((r) => keep.has(r.id));
  }
  reqs = [...reqs].sort((a, b) => nat(a.id, b.id));
  const count = (s) => reqs.filter((r) => r.status === s).length;
  return {
    framework, audit, baseline, asOf, requirements: reqs,
    total: reqs.length, covered: count('covered'), inherited: count('inherited'), gaps: count('gap'),
  };
}

// ---- Q2 adopt ------------------------------------------------------------------------------------

/** Requirements of `framework` already met through a covered 1-hop crosswalk neighbour. */
export function adopt(g, { framework, asOf }) {
  const rows = g.q('q2_adopt', { framework, as_of: asOf });
  const byReq = new Map();
  for (const r of rows) {
    if (!byReq.has(r.requirement)) byReq.set(r.requirement, { requirement: r.requirement, title: r.title, via: new Map(), paths: [] });
    const it = byReq.get(r.requirement);
    it.paths.push({ nodes: r.nodes, rels: r.rels });
    if (!it.via.has(r.neighbour)) it.via.set(r.neighbour, new Map());
    const ctrls = it.via.get(r.neighbour);
    if (!ctrls.has(r.control)) ctrls.set(r.control, new Map());
    ctrls.get(r.control).set(r.evidence, r.expires_at);
  }
  const items = natSorted(byReq.keys()).map((id) => {
    const it = byReq.get(id);
    return {
      requirement: id,
      title: it.title,
      paths: it.paths,
      via: natSorted(it.via.keys()).map((n) => ({
        neighbour: n,
        controls: natSorted(it.via.get(n).keys()).map((c) => ({
          control: c,
          evidence: natSorted(it.via.get(n).get(c).keys()).map((e) => ({ id: e, expires: it.via.get(n).get(c).get(e) })),
        })),
      })),
    };
  });
  const total = g.run('MATCH (r:Requirement {framework: $f}) RETURN count(r) AS n', { f: framework }).rows[0].n;
  return { framework, asOf, active: total, inheritedCount: items.length, items };
}

// ---- Q3 blast radius -----------------------------------------------------------------------------

function union(rows) {
  const out = {};
  for (const r of rows) (out[r.kind] ||= []).push(r.data);
  return out;
}

/** What breaks if evidence expiring in (asOf, until] is not renewed. */
export function blast(g, { asOf, until }) {
  const u = union(g.q('q3_blast', { as_of: asOf, until }));
  const expiring = (u.expiring || []).sort((a, b) => nat(a.evidence, b.evidence));
  const broken = (u.broken || []).sort((a, b) => nat(a.requirement, b.requirement));
  const audits = (u.audit || []).filter((a) => a.affected).sort((a, b) => nat(a.audit, b.audit));
  const byFw = {};
  for (const fw of FRAMEWORKS) byFw[fw] = broken.filter((b) => b.framework === fw);
  return {
    asOf, until, windowDays: daysBetween(asOf, until),
    expiring, broken, audits, byFramework: byFw,
    counts: Object.fromEntries(FRAMEWORKS.map((fw) => [fw, byFw[fw].length])),
    controlsLeft: natSorted((u.control_left || []).map((d) => d.control)),
    brokenNotInherited: broken.filter((b) => !b.still_inherited),
  };
}

// ---- Q4 reuse ------------------------------------------------------------------------------------

export function reuse(g, { asOf, top = null }) {
  const rows = g.q('q4_reuse', { as_of: asOf }).map((r, i) => ({ rank: i + 1, ...r }));
  return top ? rows.slice(0, top) : rows;
}

// ---- Q6 owner risk -------------------------------------------------------------------------------

export function ownerRisk(g, { asOf }) {
  const u = union(g.q('q6_owner_risk', { as_of: asOf }));
  const depBy = {};
  for (const d of u.dependent || []) (depBy[d.person] ||= []).push(d);
  const people = {};
  for (const d of (u.person || []).sort((a, b) => nat(a.person, b.person))) {
    const deps = depBy[d.person] || [];
    people[d.person] = {
      id: d.person, name: d.name,
      controls: natSorted(d.controls_solely_owned),
      requirementsMapped: natSorted(d.requirements_mapped),
      dependent: deps.sort((a, b) => nat(a.requirement, b.requirement)),
      systems: d.systems_touched.sort(),
      highSystems: d.high_criticality_systems.sort(),
      highControls: natSorted(d.controls_touching_high_systems),
      audits: [...new Set(deps.flatMap((x) => x.audits))].sort(),
    };
  }
  const ranking = Object.values(people)
    .filter((p) => p.controls.length)
    .sort((a, b) => b.controls.length - a.controls.length || nat(a.id, b.id));
  const unowned = (u.unowned || []).sort((a, b) => nat(a.control, b.control));
  return { people, ranking, unowned };
}

// ---- explain, proposals, claim checks ------------------------------------------------------------

export function explain(g, { requirement, asOf }) {
  const u = union(g.q('explain', { requirement, as_of: asOf }));
  if (!u.summary) throw new Error(`no requirement ${requirement}`);
  const paths = (u.path || []).sort((a, b) => nat(a.control, b.control) || nat(a.evidence || '', b.evidence || ''));
  const inherited = u.inherited || [];
  return { summary: u.summary[0], paths, inherited, proposals: (u.proposal || []).sort((a, b) => nat(a.proposal, b.proposal)) };
}

export function proposals(g) {
  return g.q('proposed_paths', { requirement: null, control: null, status: null });
}

export function decisions(g) {
  return g.run(
    `MATCH (d:Decision)-[:ON]->(p:Proposal)
     RETURN d.id AS id, d.outcome AS outcome, d.reason AS reason, d.by AS by, toString(d.at) AS at, p.id AS proposal
     ORDER BY d.at DESC, d.id`,
  ).rows;
}

/** Re-run one cited path: does it exist, and is it valid at asOf? */
export function checkPath(g, { nodes, rels, asOf }) {
  const row = g.q('check_path', { nodes, rels, as_of: asOf })[0];
  return { exists: !!row.exists, valid: !!row.valid, problems: [...new Set(row.problems || [])] };
}

// ---- helpers for the UI --------------------------------------------------------------------------

/** 'Label:id' reference -> {label, id} (the id may contain colons). */
export function splitRef(ref) {
  const i = ref.indexOf(':');
  return { label: ref.slice(0, i), id: ref.slice(i + 1) };
}

/** Short display name for a requirement id: '800-171:03.05.03' -> '03.05.03'. */
export function shortId(id) {
  const m = /^(?:800-53|800-171|CSF):(.+)$/.exec(id);
  return m ? m[1] : id;
}

export function fwOf(id) {
  const m = /^(800-53|800-171|CSF):/.exec(id);
  return m ? m[1] : null;
}
