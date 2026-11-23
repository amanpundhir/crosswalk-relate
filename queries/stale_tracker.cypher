// stale_tracker: the legacy spreadsheet (:TrackerRow) next to what the graph knows about the same control.
//
// Parameters:
//   $as_of  'YYYY-MM-DD'  the demo date (Meta.as_of; never the system clock)
//
// One row per tracker row (the row says, in free text, "Compliant", "In progress", "Gap"): the control it is
// about, who owns it in the graph, every evidence item that proves it (valid at $as_of or not), the
// requirements it has an approved SATISFIES to, and the mapping proposals about it.
// crosswalk.queries.stale decides which "Compliant" rows the graph contradicts and builds the receipts.
MATCH (t:TrackerRow)-[:ABOUT]->(c:Control)
RETURN t.id AS tracker,
       c.id AS control,
       c.title AS title,
       coalesce(c.adopted, false) AS adopted,
       c.status AS control_status,
       t.status_text AS status_text,
       t.owner AS tracker_owner,
       toString(t.last_reviewed) AS last_reviewed,
       t.requirements AS requirements,
       [(o:Person)-[:OWNS]->(c) | o.id] AS owners,
       [(e:Evidence)-[:PROVES]->(c) | {evidence: e.id, expires_at: toString(e.expires_at),
                                        valid: e.expires_at > date($as_of)}] AS evidence,
       [(c)-[:SATISFIES]->(r:Requirement) | r.id] AS satisfies,
       [(p:Proposal {kind: 'map'})-[:ABOUT]->(c) | {proposal: p.id, status: p.status,
                                                     requirement: [(p)-[:TARGET]->(q:Requirement) | q.id][0]}] AS proposals
