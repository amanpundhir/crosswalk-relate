// Q5 graph context for re-ranking mapping candidates of one control (tagged union: kind, data).
//
// Parameters:
//   $control    control id
//   $framework  framework of the candidates ('800-53' ...)
//   $ignore_own true = leave-one-out: ignore the control's OWN SATISFIES edges and its OWN proposals and
//               decisions (so an evaluation cannot read the answer off the graph)
//
//   family     candidates' family already holds an approved mapping from ANOTHER control of the same policy.
//              path: Control <-MANDATES- Policy -MANDATES-> Control -SATISFIES-> Requirement -PART_OF-> Family
//              (the candidate is any requirement of that family; the path is extended to it by the caller)
//   crosswalk  requirement the control already satisfies, with its EQUIVALENT_TO neighbours in $framework.
//              path: Control -SATISFIES-> Requirement -EQUIVALENT_TO- Requirement
//   rejected   a human rejected a proposal of this control to this requirement.
//              path: Control <-ABOUT- Proposal -TARGET-> Requirement   (the Decision is the reason)
CALL (*) {
  MATCH (c:Control {id: $control})<-[:MANDATES]-(p:Policy)-[:MANDATES]->(o:Control)
  WHERE o.id <> c.id
  MATCH (o)-[:SATISFIES]->(q:Requirement {framework: $framework})-[:PART_OF]->(f:Family)
  WITH f, collect(DISTINCT {
         sibling: o.id, requirement: q.id,
         nodes: ['Control:' + c.id, 'Policy:' + p.id, 'Control:' + o.id, 'Requirement:' + q.id, 'Family:' + f.id],
         rels: ['MANDATES<-', 'MANDATES', 'SATISFIES', 'PART_OF']}) AS via
  RETURN 'family' AS kind, {family: f.id, via: via} AS data
  UNION ALL
  MATCH (c:Control {id: $control})-[:SATISFIES]->(q:Requirement)-[:EQUIVALENT_TO]-(n:Requirement {framework: $framework})
  WHERE NOT $ignore_own
  RETURN 'crosswalk' AS kind, {
         candidate: n.id, via: q.id,
         nodes: ['Control:' + c.id, 'Requirement:' + q.id, 'Requirement:' + n.id],
         rels: ['SATISFIES', 'EQUIVALENT_TO']} AS data
  UNION ALL
  MATCH (c:Control {id: $control})<-[:ABOUT]-(p:Proposal)-[:TARGET]->(q:Requirement {framework: $framework})
  MATCH (d:Decision {outcome: 'rejected'})-[:ON]->(p)
  WHERE NOT $ignore_own
  RETURN 'rejected' AS kind, {
         candidate: q.id, proposal: p.id, decision: d.id, reason: d.reason, by: d.by,
         nodes: ['Control:' + c.id, 'Proposal:' + p.id, 'Requirement:' + q.id],
         rels: ['ABOUT<-', 'TARGET']} AS data
}
RETURN kind, data
