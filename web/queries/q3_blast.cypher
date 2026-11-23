// Q3 blast radius of evidence that expires inside a window (spec v1.1, section 5).
//
// Parameters:
//   $as_of   'YYYY-MM-DD'  the demo date (Meta.as_of; never the system clock)
//   $until   'YYYY-MM-DD'  cutoff: as_of + N days, or an audit date
//
// Window: evidence that is valid at $as_of (expires_at > $as_of) but expires on or before $until
// (expires_at <= $until).  "Gone after the window" = expires_at <= $until.
//
// BLAST RADIUS = requirements covered directly now (adopted control, approved SATISFIES, evidence
// valid at $as_of) that LOSE direct coverage because no covering control keeps evidence valid past
// $until.  An expired-but-replaced item (decoy) therefore never shows up.  `still_inherited` is
// evaluated on the post-expiry state: a 1-hop EQUIVALENT_TO neighbour still covered after $until
// (never for 800-53).
//
// AFFECTED AUDIT = the audit requests at least one expiring evidence item OR its framework contains
// at least one broken requirement (both reasons are returned).
//
// The result is a tagged union: every row is (kind, data) with
//   kind 'expiring'      one row per expiring evidence item
//   kind 'control_left'  one row per adopted control left with no valid evidence after $until
//   kind 'broken'        one row per broken requirement, with the lost paths and (if any) the
//                        inherited paths that still hold it up
//   kind 'audit'         one row per audit with the two reasons and an `affected` flag
// Paths are {nodes, rels} lists: 'Label:id' references and traversal tokens ('<-' = against the
// stored direction); crosswalk.paths.path_id turns them into path ids.

// ---- expiring evidence, the controls it leaves bare, the audits that request it ----------------
MATCH (e:Evidence)
WHERE e.expires_at > date($as_of) AND e.expires_at <= date($until)
OPTIONAL MATCH (e)-[:PROVES]->(c:Control {adopted: true})
OPTIONAL MATCH (c)<-[:PROVES]-(keep:Evidence)
WHERE keep.expires_at > date($until)
WITH e, c, count(keep) AS replacements
WITH e,
     collect(c.id) AS proves,
     collect(CASE WHEN replacements = 0 THEN c.id END) AS left_bare,
     collect(CASE WHEN replacements > 0 THEN c.id END) AS with_replacement
OPTIONAL MATCH (a:Audit)-[:REQUESTS]->(e)
WITH e, proves, left_bare, with_replacement, collect(a.id) AS requested_by
RETURN 'expiring' AS kind,
       {evidence: e.id,
        expires_at: toString(e.expires_at),
        proves: proves,
        controls_left_without_valid_evidence: left_bare,
        controls_with_replacement: with_replacement,
        requested_by: requested_by,
        paths: [x IN proves | {nodes: ['Evidence:' + e.id, 'Control:' + x], rels: ['PROVES']}]} AS data

UNION ALL

// ---- adopted controls that have valid evidence now but none after $until -----------------------
MATCH (c:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE e.expires_at > date($as_of)
WITH DISTINCT c
OPTIONAL MATCH (c)<-[:PROVES]-(keep:Evidence)
WHERE keep.expires_at > date($until)
WITH c, count(keep) AS remaining
WHERE remaining = 0
RETURN 'control_left' AS kind, {control: c.id} AS data

UNION ALL

// ---- broken requirements: covered now, nothing left after $until --------------------------------
// `survivors` counts covering (control, evidence) pairs whose evidence outlives the window.
MATCH (r:Requirement)<-[:SATISFIES]-(c:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE e.expires_at > date($as_of)
WITH r,
     collect(DISTINCT c.id) AS controls_lost,
     collect({c: c.id, e: e.id}) AS lost_pairs,
     count(CASE WHEN e.expires_at > date($until) THEN 1 END) AS survivors
WHERE survivors = 0
// would the requirement still be met through one crosswalk hop after the window?
OPTIONAL MATCH (r)-[:EQUIVALENT_TO]-(n:Requirement)<-[:SATISFIES]-(c2:Control {adopted: true})<-[:PROVES]-(e2:Evidence)
WHERE r.framework <> '800-53' AND e2.expires_at > date($until)
WITH r, controls_lost, lost_pairs,
     collect(CASE WHEN n IS NOT NULL THEN {n: n.id, c: c2.id, e: e2.id} END) AS inh
RETURN 'broken' AS kind,
       {requirement: r.id,
        framework: r.framework,
        title: r.title,
        controls_lost: controls_lost,
        evidence_lost: [p IN lost_pairs | p.e],
        still_inherited: size(inh) > 0,
        inherited_via: [x IN inh | x.n],
        paths: [p IN lost_pairs | {nodes: ['Requirement:' + r.id, 'Control:' + p.c, 'Evidence:' + p.e],
                                   rels: ['SATISFIES<-', 'PROVES<-']}],
        inherited_paths: [x IN inh | {nodes: ['Requirement:' + r.id, 'Requirement:' + x.n,
                                              'Control:' + x.c, 'Evidence:' + x.e],
                                      rels: ['EQUIVALENT_TO', 'SATISFIES<-', 'PROVES<-']}]} AS data

UNION ALL

// ---- audits: requests an expiring item, or its framework has broken requirements ---------------
MATCH (a:Audit)-[:SCOPES]->(f:Framework)
OPTIONAL MATCH (a)-[:REQUESTS]->(x:Evidence)
WHERE x.expires_at > date($as_of) AND x.expires_at <= date($until)
WITH a, f, collect(x.id) AS requested_expiring
OPTIONAL MATCH (q:Requirement {framework: f.id})<-[:SATISFIES]-(:Control {adopted: true})<-[:PROVES]-(v:Evidence)
WHERE v.expires_at > date($as_of)
WITH a, f, requested_expiring, q,
     count(CASE WHEN v.expires_at > date($until) THEN 1 END) AS survivors
WITH a, f, requested_expiring,
     count(CASE WHEN q IS NOT NULL AND survivors = 0 THEN 1 END) AS broken_in_framework
RETURN 'audit' AS kind,
       {audit: a.id,
        name: a.name,
        framework: f.id,
        date: toString(a.date),
        requests_expiring_evidence: requested_expiring,
        broken_requirements_in_framework: broken_in_framework,
        affected: size(requested_expiring) > 0 OR broken_in_framework > 0,
        paths: [y IN requested_expiring | {nodes: ['Audit:' + a.id, 'Evidence:' + y], rels: ['REQUESTS']}]} AS data
