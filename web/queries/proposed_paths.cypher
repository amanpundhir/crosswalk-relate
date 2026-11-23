// proposed_paths: mapping proposals as citable paths, so an agent CAN cite "this control is proposed for
// this requirement" and the claim checker can answer "proposed, not approved" instead of "unknown".
//
// A proposed path is  Requirement <-TARGET- Proposal -ABOUT-> Control  (path tokens 'TARGET<-', 'ABOUT').
// check_path.cypher reports a pending proposal on a path as "mapping C -> R is proposed (PR-n), not approved".
//
// Parameters (all optional, pass null to ignore):
//   $requirement  full requirement id, e.g. '800-171:03.05.03'
//   $control      control id, e.g. 'CTRL-PWP-4'
//   $status       'pending' | 'approved' | 'rejected'
MATCH (p:Proposal {kind: 'map'})-[:TARGET]->(r:Requirement)
MATCH (p)-[:ABOUT]->(c:Control)
WHERE ($requirement IS NULL OR r.id = $requirement)
  AND ($control IS NULL OR c.id = $control)
  AND ($status IS NULL OR p.status = $status)
OPTIONAL MATCH (p)-[:BY]->(a:Agent)
OPTIONAL MATCH (d:Decision)-[:ON]->(p)
RETURN p.id AS proposal, p.status AS status, p.verified AS verified, p.rationale AS rationale,
       a.id AS by, c.id AS control, r.id AS requirement, d.outcome AS decision, d.reason AS decision_reason,
       ['Requirement:' + r.id, 'Proposal:' + p.id, 'Control:' + c.id] AS nodes,
       ['TARGET<-', 'ABOUT'] AS rels
ORDER BY p.id
