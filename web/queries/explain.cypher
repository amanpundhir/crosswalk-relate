// Explain one requirement: requirement <- control <- evidence, with dates, owners and validity.
//
// Parameters:
//   $requirement  full requirement id, e.g. '800-171:03.05.03'
//   $as_of        'YYYY-MM-DD' (Meta.as_of; never the system clock)
//
// A direct path is VALID when the mapping is approved (approved_by present), the control is adopted
// and its evidence has expires_at > $as_of.  Expired paths are returned too (valid = false) so the
// answer can say why a requirement is NOT covered.  INHERITED paths are only returned for a
// non-800-53 requirement with no valid direct path (spec v1.1, 1 hop).
//
// Tagged-union result, one (kind, data) row each:
//   'summary'   exactly one row if the requirement exists: title, framework, number of valid direct paths
//   'path'      one row per (adopted control with a SATISFIES to it, evidence it has); a control with
//               no evidence at all gets one row with evidence = null
//   'inherited' one row per proving path through a covered 1-hop EQUIVALENT_TO neighbour
//   'proposal'  proposed (not approved) mappings aimed at this requirement, with any human decision
// Paths are {nodes, rels}: 'Label:id' references and traversal tokens ('<-' = walked against the
// stored direction); crosswalk.paths.path_id turns them into path ids.
MATCH (r:Requirement {id: $requirement})
OPTIONAL MATCH (r)<-[:SATISFIES]-(:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE e.expires_at > date($as_of)
WITH r, count(e) AS valid_paths
RETURN 'summary' AS kind,
       {requirement: r.id, framework: r.framework, title: r.title, direct_valid_paths: valid_paths} AS data

UNION ALL

MATCH (r:Requirement {id: $requirement})<-[s:SATISFIES]-(c:Control {adopted: true})
OPTIONAL MATCH (c)<-[:PROVES]-(e:Evidence)
RETURN 'path' AS kind,
       {control: c.id,
        control_title: c.title,
        control_status: c.status,
        control_owners: [(o:Person)-[:OWNS]->(c) | o.id],
        mapping_approved_by: s.approved_by,
        mapping_approved_at: toString(s.approved_at),
        evidence: e.id,
        evidence_kind: e.kind,
        evidence_owners: [(q:Person)-[:OWNS]->(e) | q.id],
        collected_at: toString(e.collected_at),
        expires_at: toString(e.expires_at),
        valid: e IS NOT NULL AND s.approved_by IS NOT NULL AND e.expires_at > date($as_of),
        nodes: CASE WHEN e IS NULL THEN ['Requirement:' + r.id, 'Control:' + c.id]
                    ELSE ['Requirement:' + r.id, 'Control:' + c.id, 'Evidence:' + e.id] END,
        rels: CASE WHEN e IS NULL THEN ['SATISFIES<-'] ELSE ['SATISFIES<-', 'PROVES<-'] END} AS data

UNION ALL

// inherited: only when there is no valid direct path (count of valid direct evidence = 0)
MATCH (r:Requirement {id: $requirement})
OPTIONAL MATCH (r)<-[:SATISFIES]-(:Control {adopted: true})<-[:PROVES]-(d:Evidence)
WHERE d.expires_at > date($as_of)
WITH r, count(d) AS direct_valid
OPTIONAL MATCH (r)-[:EQUIVALENT_TO]-(n:Requirement)<-[s2:SATISFIES]-(c:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE direct_valid = 0 AND r.framework <> '800-53' AND e.expires_at > date($as_of)
WITH r, n, s2, c, e
WHERE n IS NOT NULL
RETURN DISTINCT 'inherited' AS kind,
       {neighbour: n.id,
        neighbour_title: n.title,
        control: c.id,
        control_title: c.title,
        mapping_approved_by: s2.approved_by,
        evidence: e.id,
        expires_at: toString(e.expires_at),
        nodes: ['Requirement:' + r.id, 'Requirement:' + n.id, 'Control:' + c.id, 'Evidence:' + e.id],
        rels: ['EQUIVALENT_TO', 'SATISFIES<-', 'PROVES<-']} AS data

UNION ALL

MATCH (p:Proposal)-[:TARGET]->(r:Requirement {id: $requirement})
MATCH (p)-[:ABOUT]->(c:Control)
OPTIONAL MATCH (d:Decision)-[:ON]->(p)
RETURN 'proposal' AS kind,
       {proposal: p.id,
        control: c.id,
        status: p.status,
        rationale: p.rationale,
        decision: d.outcome,
        decided_by: d.by,
        decided_at: toString(d.at),
        reason: d.reason} AS data
