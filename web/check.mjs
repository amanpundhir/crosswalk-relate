// Node check of the browser build: loads web/data/graph.cypher into the SAME Relate WASM binary the
// site ships (web/vendor/relate), runs the SAME Cypher (web/queries/*.cypher) through the SAME JS the
// page uses (web/js/analysis.js) and compares the totals with the oracle (eval/ground_truth.json),
// i.e. with what `crosswalk coverage` / `blast` / ... print.
//
//   node web/check.mjs        (exit code 1 if anything differs)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { initSync, RelateDb } from './vendor/relate/relate.js';
import { GraphDb } from './js/graphdb.js';
import * as A from './js/analysis.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => fs.readFileSync(path.join(here, p), 'utf8');
const gt = JSON.parse(fs.readFileSync(path.join(here, '..', 'eval', 'ground_truth.json'), 'utf8'));
const meta = JSON.parse(read('data/meta.json'));

initSync({ module: fs.readFileSync(path.join(here, 'vendor/relate/relate_bg.wasm')) });
const g = new GraphDb(RelateDb);
g.setScript(read('data/graph.cypher'));
g.setQueries(Object.fromEntries(meta.queries.map((n) => [n, read(`queries/${n}.cypher`)])));
const ms = g.load();
const asOf = A.readAsOf(g);

let failures = 0;
// compare as JSON with object keys sorted (the oracle and the browser order keys differently)
const canon = (v) => JSON.stringify(v, (_, x) => (x && typeof x === 'object' && !Array.isArray(x)
  ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : 1))) : x));
const eq = (label, got, want) => {
  const ok = canon(got) === canon(want);
  if (!ok) failures++;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}: ${JSON.stringify(got)}${ok ? '' : `  (oracle ${JSON.stringify(want)})`}`);
};

const nodes = g.run('MATCH (n) RETURN count(n) AS n').rows[0].n;
const rels = g.run('MATCH ()-[r]->() RETURN count(r) AS n').rows[0].n;
console.log(`Relate WASM loaded ${g.statements.length} statements in ${ms} ms: ${nodes} nodes, ${rels} relationships, as_of ${asOf}`);
eq('node count vs meta.json', [nodes, rels], [meta.total_nodes, meta.total_relationships]);

console.log('\nCoverage (q1_coverage.cypher)');
for (const fw of A.FRAMEWORKS) {
  const c = A.coverage(g, { framework: fw, asOf });
  const o = gt.q1_coverage.by_framework[fw].counts;
  eq(`${fw}  total ${c.total}  covered/inherited/gaps`, [c.covered, c.inherited, c.gaps], [o.direct, o.inherited, o.gap]);
}
for (const [id, o] of Object.entries(gt.q1_coverage.by_audit)) {
  const c = A.coverage(g, { audit: id, asOf });
  eq(`${id} (${c.framework}${c.baseline ? ' ' + c.baseline : ''}) scope ${c.total}  covered/inherited/gaps`,
    [c.covered, c.inherited, c.gaps], [o.counts.direct, o.counts.inherited, o.counts.gap]);
}

console.log('\nAdopt (q2_adopt.cypher)');
for (const fw of ['800-171', 'CSF']) {
  eq(`${fw} inherited requirements`, A.adopt(g, { framework: fw, asOf }).inheritedCount, gt.q2_adopt[fw].inherited_count);
}

console.log('\nBlast (q3_blast.cypher)');
const b30 = A.blast(g, { asOf, until: A.addDays(asOf, 30) });
eq('30 days: broken by framework', b30.counts, gt.q3_blast_30d.broken_counts);
eq('30 days: broken and not inherited', b30.brokenNotInherited.map((b) => b.requirement).sort(), [...gt.q3_blast_30d.broken_and_not_inherited].sort());
eq('30 days: affected audits', b30.audits.map((a) => a.audit).sort(), gt.q3_blast_30d.affected_audits.map((a) => a.audit).sort());
for (const [id, o] of Object.entries(gt.q3_blast_until_audit)) {
  const b = A.blast(g, { asOf, until: o.cutoff });
  eq(`before ${id} (${o.cutoff}): broken by framework`, b.counts, o.broken_counts);
}

console.log('\nReuse (q4_reuse.cypher) and owner risk (q6_owner_risk.cypher)');
const ru = A.reuse(g, { asOf });
eq('top 3 reused evidence', ru.slice(0, 3).map((r) => r.evidence), gt.q4_reuse.slice(0, 3).map((r) => r.evidence));
const or = A.ownerRisk(g, { asOf });
eq('Dana sole-owned controls', or.people['P-dana-okafor'].controls, [...gt.q6_owner_risk.people['P-dana-okafor'].controls_solely_owned].sort(A.nat));
eq('unowned controls', or.unowned.map((u) => u.control), gt.q6_owner_risk.unowned_controls);
eq('sole-owner ranking head', or.ranking.slice(0, 3).map((p) => [p.id, p.controls.length]),
  gt.q6_owner_risk.sole_owner_ranking.slice(0, 3).map((p) => [p.person, p.sole_owned_count]));

console.log('\nLive catch (check_path.cypher on the recorded answer)');
const rec = JSON.parse(read('data/live-catch.json'));
const verdicts = rec.paths.map((p) => ({ id: p.id, ...A.checkPath(g, { nodes: p.nodes, rels: p.rels, asOf }) }));
for (const v of verdicts) console.log(`     ${v.id} exists=${v.exists} valid=${v.valid} ${v.problems.join(' | ')}`);
eq('EV-044 path fails as expired', verdicts[0].valid === false && /expired/.test(verdicts[0].problems.join()), true);
eq('PR-005 path is proposed, not approved', verdicts[1].valid === false && /proposed/.test(verdicts[1].problems.join()), true);

console.log('\nWhat-if (in memory) and reset');
const before = A.coverage(g, { framework: '800-171', asOf });
g.run('MATCH (e:Evidence {id: $id}) SET e.expires_at = date($d)', { id: 'EV-100', d: A.addDays(asOf, -1) });
const after = A.coverage(g, { framework: '800-171', asOf });
console.log(`     expire EV-100: 800-171 covered ${before.covered} -> ${after.covered}, gaps ${before.gaps} -> ${after.gaps}`);
eq('expiring EV-100 reduces coverage', after.covered < before.covered, true);
g.run('MATCH (p:Person {id: $id}) DETACH DELETE p', { id: 'P-dana-okafor' });
eq('removing Dana leaves her 6 controls unowned', A.ownerRisk(g, { asOf }).unowned.length, 1 + 6);
g.load();
const reset = A.coverage(g, { framework: '800-171', asOf });
eq('reset restores 800-171 coverage', [reset.covered, reset.inherited, reset.gaps], [before.covered, before.inherited, before.gaps]);

const c171 = A.coverage(g, { framework: '800-171', asOf });
console.log(`\nTOTALS 800-171 (browser WASM): ${c171.total} requirements, ${c171.covered} covered, ${c171.inherited} inherited, ${c171.gaps} gaps`);
console.log(failures ? `\n${failures} CHECK(S) FAILED` : '\nall checks passed: browser numbers equal the CLI/oracle');
process.exit(failures ? 1 : 0);
