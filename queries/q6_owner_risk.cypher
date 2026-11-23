// Q6 owner risk: "what if <person> leaves?"
//
// Parameters:
//   $as_of  'YYYY-MM-DD' (Meta.as_of; never the system clock)
//
// SOLE-OWNED control  an adopted control with exactly one OWNS relationship (that person).
// SOLELY DEPENDENT requirement  covered directly now (valid evidence at $as_of) where EVERY covering
//                    control is sole-owned by the same person: if she leaves, coverage has no owner.
// UNOWNED control    an adopted control with no OWNS relationship at all.
//
// Tagged-union result, one (kind, data) row each:
//   'person'     every person: controls solely owned, requirements those controls map to (all
//                approved mappings), systems touched, high-criticality systems, controls touching them
//   'dependent'  every solely-dependent requirement with the owner, the audits that scope its
//                framework, and the paths Person -OWNS-> Control -SATISFIES-> Requirement
//   'unowned'    every adopted control without an owner
MATCH (p:Person)
OPTIONAL MATCH (p)-[:OWNS]->(c:Control {adopted: true})
WHERE size([(o:Person)-[:OWNS]->(c) | o]) = 1
OPTIONAL MATCH (c)-[:SATISFIES]->(r:Requirement)
OPTIONAL MATCH (c)-[:APPLIES_TO]->(s:System)
WITH p,
     collect(DISTINCT c.id) AS controls,
     collect(DISTINCT r.id) AS requirements,
     collect(DISTINCT s.id) AS systems,
     collect(DISTINCT CASE WHEN s.criticality = 'high' THEN s.id END) AS high_systems,
     collect(DISTINCT CASE WHEN s.criticality = 'high' THEN c.id END) AS high_controls,
     collect(DISTINCT CASE WHEN c IS NOT NULL THEN {nodes: ['Person:' + p.id, 'Control:' + c.id], rels: ['OWNS']} END) AS own_paths
RETURN 'person' AS kind,
       {person: p.id,
        name: p.name,
        controls_solely_owned: controls,
        requirements_mapped: requirements,
        systems_touched: systems,
        high_criticality_systems: high_systems,
        controls_touching_high_systems: high_controls,
        paths: own_paths} AS data

UNION ALL

MATCH (r:Requirement)<-[:SATISFIES]-(c:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE e.expires_at > date($as_of)
WITH r, collect(DISTINCT c) AS covering
WITH r, covering, [x IN covering | [(o:Person)-[:OWNS]->(x) | o.id]] AS owner_lists
WHERE all(l IN owner_lists WHERE size(l) = 1 AND l[0] = owner_lists[0][0])
RETURN 'dependent' AS kind,
       {requirement: r.id,
        framework: r.framework,
        person: owner_lists[0][0],
        controls: [x IN covering | x.id],
        audits: [(a:Audit)-[:SCOPES]->(:Framework {id: r.framework}) | a.id],
        paths: [x IN covering | {nodes: ['Person:' + owner_lists[0][0], 'Control:' + x.id, 'Requirement:' + r.id],
                                 rels: ['OWNS', 'SATISFIES']}]} AS data

UNION ALL

MATCH (c:Control {adopted: true})
WHERE NOT (c)<-[:OWNS]-(:Person)
RETURN 'unowned' AS kind, {control: c.id, title: c.title, status: c.status} AS data
