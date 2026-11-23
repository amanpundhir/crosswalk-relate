// all_paths: every path SHAPE any Crosswalk command can cite, enumerated over the whole graph.
//
// A path id is a one-way hash, so a fresh process (the CLI `crosswalk check`, a restarted MCP server) can
// only resolve an id by rebuilding the path.  crosswalk.claims.discover runs this once and registers every
// (nodes, rels) pair it returns.  It deliberately returns a SUPERSET of what the read commands emit: no
// date, adoption, approval or status filter, so expired evidence, unadopted controls and pending proposals
// are all included (check_path.cypher judges validity later, at the date of the check).
//
// Shapes (the command that emits them in brackets):
//   Requirement <-SATISFIES- Control [<-PROVES- Evidence]                      coverage, explain, blast, stale
//   Requirement -EQUIVALENT_TO- Requirement <-SATISFIES- Control <-PROVES- Evidence    adopt, explain, blast
//   Evidence -PROVES-> Control [-SATISFIES-> Requirement [-EQUIVALENT_TO- Requirement]]  reuse, evidence, stale
//   Audit -REQUESTS-> Evidence [-PROVES-> Control]                             blast, evidence
//   Person -OWNS-> Control [-SATISFIES-> Requirement]                          owners
//   Proposal -ABOUT-> x, Proposal -TARGET-> y, Requirement <-TARGET- Proposal -ABOUT-> Control,
//   Control <-ABOUT- Proposal -TARGET-> Requirement                            explain, decisions, suggest
//   Decision -ON-> Proposal -ABOUT-> x / -TARGET-> y                           decisions
//   TrackerRow -ABOUT-> Control                                                stale
//   Control -SATISFIES-> Requirement -EQUIVALENT_TO- Requirement               suggest (crosswalk signal)
// The long suggest "family" path (Control <-MANDATES- Policy -MANDATES-> Control -SATISFIES-> Requirement
// -PART_OF-> Family <-PART_OF- Requirement) and the absence receipts (NO_OWNS<-, NO_PROVES<-, NO_SATISFIES)
// are produced by crosswalk.claims.discover itself.
MATCH (r:Requirement)<-[:SATISFIES]-(c:Control)
RETURN ['Requirement:' + r.id, 'Control:' + c.id] AS nodes, ['SATISFIES<-'] AS rels

UNION ALL

MATCH (r:Requirement)<-[:SATISFIES]-(c:Control)<-[:PROVES]-(e:Evidence)
RETURN ['Requirement:' + r.id, 'Control:' + c.id, 'Evidence:' + e.id] AS nodes, ['SATISFIES<-', 'PROVES<-'] AS rels

UNION ALL

MATCH (r:Requirement)-[:EQUIVALENT_TO]-(n:Requirement)<-[:SATISFIES]-(c:Control)<-[:PROVES]-(e:Evidence)
RETURN ['Requirement:' + r.id, 'Requirement:' + n.id, 'Control:' + c.id, 'Evidence:' + e.id] AS nodes,
       ['EQUIVALENT_TO', 'SATISFIES<-', 'PROVES<-'] AS rels

UNION ALL

MATCH (e:Evidence)-[:PROVES]->(c:Control)
RETURN ['Evidence:' + e.id, 'Control:' + c.id] AS nodes, ['PROVES'] AS rels

UNION ALL

MATCH (e:Evidence)-[:PROVES]->(c:Control)-[:SATISFIES]->(d:Requirement)
RETURN ['Evidence:' + e.id, 'Control:' + c.id, 'Requirement:' + d.id] AS nodes, ['PROVES', 'SATISFIES'] AS rels

UNION ALL

MATCH (e:Evidence)-[:PROVES]->(c:Control)-[:SATISFIES]->(d:Requirement)-[:EQUIVALENT_TO]-(h:Requirement)
RETURN ['Evidence:' + e.id, 'Control:' + c.id, 'Requirement:' + d.id, 'Requirement:' + h.id] AS nodes,
       ['PROVES', 'SATISFIES', 'EQUIVALENT_TO'] AS rels

UNION ALL

MATCH (a:Audit)-[:REQUESTS]->(e:Evidence)
RETURN ['Audit:' + a.id, 'Evidence:' + e.id] AS nodes, ['REQUESTS'] AS rels

UNION ALL

MATCH (a:Audit)-[:REQUESTS]->(e:Evidence)-[:PROVES]->(c:Control)
RETURN ['Audit:' + a.id, 'Evidence:' + e.id, 'Control:' + c.id] AS nodes, ['REQUESTS', 'PROVES'] AS rels

UNION ALL

MATCH (p:Person)-[:OWNS]->(c:Control)
RETURN ['Person:' + p.id, 'Control:' + c.id] AS nodes, ['OWNS'] AS rels

UNION ALL

MATCH (p:Person)-[:OWNS]->(c:Control)-[:SATISFIES]->(r:Requirement)
RETURN ['Person:' + p.id, 'Control:' + c.id, 'Requirement:' + r.id] AS nodes, ['OWNS', 'SATISFIES'] AS rels

UNION ALL

MATCH (p:Person)-[:OWNS]->(e:Evidence)
RETURN ['Person:' + p.id, 'Evidence:' + e.id] AS nodes, ['OWNS'] AS rels

UNION ALL

MATCH (p:Proposal)-[:ABOUT]->(x)
RETURN ['Proposal:' + p.id, labels(x)[0] + ':' + x.id] AS nodes, ['ABOUT'] AS rels

UNION ALL

MATCH (p:Proposal)-[:TARGET]->(x)
RETURN ['Proposal:' + p.id, labels(x)[0] + ':' + x.id] AS nodes, ['TARGET'] AS rels

UNION ALL

MATCH (r:Requirement)<-[:TARGET]-(p:Proposal)-[:ABOUT]->(c:Control)
RETURN ['Requirement:' + r.id, 'Proposal:' + p.id, 'Control:' + c.id] AS nodes, ['TARGET<-', 'ABOUT'] AS rels

UNION ALL

MATCH (c:Control)<-[:ABOUT]-(p:Proposal)-[:TARGET]->(r:Requirement)
RETURN ['Control:' + c.id, 'Proposal:' + p.id, 'Requirement:' + r.id] AS nodes, ['ABOUT<-', 'TARGET'] AS rels

UNION ALL

MATCH (d:Decision)-[:ON]->(p:Proposal)-[:ABOUT]->(x)
RETURN ['Decision:' + d.id, 'Proposal:' + p.id, labels(x)[0] + ':' + x.id] AS nodes, ['ON', 'ABOUT'] AS rels

UNION ALL

MATCH (d:Decision)-[:ON]->(p:Proposal)-[:TARGET]->(x)
RETURN ['Decision:' + d.id, 'Proposal:' + p.id, labels(x)[0] + ':' + x.id] AS nodes, ['ON', 'TARGET'] AS rels

UNION ALL

MATCH (t:TrackerRow)-[:ABOUT]->(c:Control)
RETURN ['TrackerRow:' + t.id, 'Control:' + c.id] AS nodes, ['ABOUT'] AS rels

UNION ALL

MATCH (c:Control)-[:SATISFIES]->(q:Requirement)-[:EQUIVALENT_TO]-(n:Requirement)
RETURN ['Control:' + c.id, 'Requirement:' + q.id, 'Requirement:' + n.id] AS nodes, ['SATISFIES', 'EQUIVALENT_TO'] AS rels
