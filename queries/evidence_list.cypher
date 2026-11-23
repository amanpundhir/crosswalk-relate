// evidence_list: every evidence item with its dates, status, requesting audits and the controls it proves.
//
// Parameters:
//   $as_of   'YYYY-MM-DD'  the demo date (Meta.as_of; never the system clock)
//   $until   'YYYY-MM-DD'  cutoff for "expiring": an audit date, an explicit --until, or as_of + 30 days
//
// status (decided here, so the CLI, the MCP tool and the tests agree):
//   'expired'   expires_at <= $as_of      already past its expiry date
//   'expiring'  $as_of < expires_at <= $until   valid today, gone by the cutoff (same rule as blast)
//   'valid'     expires_at > $until       still valid at the cutoff
// An evidence item is valid at a date d when expires_at > d (the rule every other query uses).
//
// One row per evidence item; filtering (audit, status) is done by crosswalk.queries.evidence.
MATCH (e:Evidence)
RETURN e.id AS evidence,
       e.kind AS kind,
       e.title AS title,
       toString(e.collected_at) AS collected_at,
       toString(e.expires_at) AS expires_at,
       CASE WHEN e.expires_at <= date($as_of) THEN 'expired'
            WHEN e.expires_at <= date($until) THEN 'expiring'
            ELSE 'valid' END AS status,
       [(o:Person)-[:OWNS]->(e) | o.id] AS owners,
       [(e)-[:PROVES]->(c:Control) | {control: c.id, adopted: coalesce(c.adopted, false)}] AS controls,
       [(a:Audit)-[:REQUESTS]->(e) | {audit: a.id, name: a.name, date: toString(a.date),
                                       framework: [(a)-[:SCOPES]->(f:Framework) | f.id][0]}] AS requested_by
