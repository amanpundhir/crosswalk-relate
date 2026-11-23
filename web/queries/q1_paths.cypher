// Q1 receipts: the direct-coverage paths behind q1_coverage.cypher (one row per path).
//
// Parameters:
//   $framework  '800-53' | '800-171' | 'CSF'
//   $as_of      'YYYY-MM-DD' (Meta.as_of; never the system clock)
//
// A requirement is covered directly when an ADOPTED control has an approved SATISFIES to it and at
// least one Evidence with expires_at > $as_of proves that control.  Each such triple is one path:
//   Requirement <-SATISFIES- Control <-PROVES- Evidence
// `nodes` are 'Label:id' references and `rels` are traversal tokens ('<-' = walked against the
// stored direction); crosswalk.paths.path_id hashes them (see src/crosswalk/paths.py).
MATCH (r:Requirement {framework: $framework})<-[s:SATISFIES]-(c:Control {adopted: true})<-[:PROVES]-(e:Evidence)
WHERE e.expires_at > date($as_of)
RETURN r.id AS requirement,
       c.id AS control,
       e.id AS evidence,
       toString(e.expires_at) AS expires_at,
       ['Requirement:' + r.id, 'Control:' + c.id, 'Evidence:' + e.id] AS nodes,
       ['SATISFIES<-', 'PROVES<-'] AS rels
