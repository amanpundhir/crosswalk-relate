// Q2 adopt a new framework: what do we already meet through the crosswalk? (spec v1.1)
//
// Parameters:
//   $framework  framework being adopted: '800-171' | 'CSF' ('800-53' returns no rows: it has no
//               inheritance, it is the framework the company mapped to)
//   $as_of      'YYYY-MM-DD' (Meta.as_of; never the system clock)
//
// A requirement R of $framework is INHERITED when
//   * it is not covered directly (no adopted control with an approved SATISFIES to R and valid
//     evidence, expires_at > $as_of), and
//   * a 1-hop EQUIVALENT_TO neighbour N (any framework, either direction) IS covered directly.
//
// One row per proving path:
//   R -EQUIVALENT_TO- N <-SATISFIES- Control <-PROVES- Evidence
// so the result is Control -> SATISFIES -> N -> EQUIVALENT_TO -> R, read backwards, with the evidence
// that keeps it valid.  `nodes`/`rels` are the path ('<-' = walked against the stored direction).
MATCH (r:Requirement {framework: $framework})
WHERE $framework <> '800-53'
  AND NOT EXISTS {
    MATCH (r)<-[:SATISFIES]-(:Control {adopted: true})<-[:PROVES]-(d:Evidence)
    WHERE d.expires_at > date($as_of)
  }
MATCH (r)-[:EQUIVALENT_TO]-(n:Requirement)<-[:SATISFIES]-(c:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE e.expires_at > date($as_of)
RETURN DISTINCT
       r.id AS requirement,
       r.title AS title,
       n.id AS neighbour,
       c.id AS control,
       e.id AS evidence,
       toString(e.expires_at) AS expires_at,
       ['Requirement:' + r.id, 'Requirement:' + n.id, 'Control:' + c.id, 'Evidence:' + e.id] AS nodes,
       ['EQUIVALENT_TO', 'SATISFIES<-', 'PROVES<-'] AS rels
