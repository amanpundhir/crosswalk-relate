// Q1 coverage of one framework, with gaps (spec v1.1, section 5).
//
// Parameters:
//   $framework  '800-53' | '800-171' | 'CSF'
//   $as_of      'YYYY-MM-DD' (the demo date, read from (:Meta).as_of; never the system clock)
//
// covered    a requirement with an approved SATISFIES from an ADOPTED control that has at
//            least one evidence item with expires_at > $as_of.
// inherited  not covered, but a 1-hop EQUIVALENT_TO neighbour is covered (as defined above).
//            Only evaluated for non-800-53 frameworks (spec: "for a non-800-53 framework").
// gap        neither.
//
// One row comes back: totals plus the per-requirement list (id, family, status, the
// controls and evidence that make it covered, and the neighbours it inherits through).
MATCH (r:Requirement {framework: $framework})-[:PART_OF]->(f:Family)
OPTIONAL MATCH (r)<-[:SATISFIES]-(c:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE e.expires_at > date($as_of)
WITH r, f, collect(DISTINCT c.id) AS controls, collect(DISTINCT e.id) AS evidence
OPTIONAL MATCH (r)-[:EQUIVALENT_TO]-(n:Requirement)<-[:SATISFIES]-(c2:Control {adopted: true})<-[:PROVES]-(e2:Evidence)
WHERE $framework <> '800-53' AND size(controls) = 0 AND e2.expires_at > date($as_of)
WITH r, f, controls, evidence, collect(DISTINCT n.id) AS via
WITH r, f, controls, evidence, via,
     CASE WHEN size(controls) > 0 THEN 'covered'
          WHEN size(via) > 0 THEN 'inherited'
          ELSE 'gap' END AS status
WITH collect({id: r.id, title: r.title, family_id: f.id, family_title: f.title, status: status,
              controls: controls, evidence: evidence, via: via}) AS requirements
RETURN $framework AS framework,
       $as_of AS as_of,
       size(requirements) AS total,
       size([x IN requirements WHERE x.status = 'covered']) AS covered,
       size([x IN requirements WHERE x.status = 'inherited']) AS inherited,
       size([x IN requirements WHERE x.status = 'gap']) AS gaps,
       requirements
