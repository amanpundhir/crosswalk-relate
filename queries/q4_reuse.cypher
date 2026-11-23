// Q4 evidence reuse: which single piece of evidence earns the most compliance credit?
//
// Parameters:
//   $as_of  'YYYY-MM-DD' (Meta.as_of; never the system clock)
//
// For every evidence item that is still valid (expires_at > $as_of):
//   controls            adopted controls it proves
//   direct requirements distinct requirements those controls satisfy (approved SATISFIES)
//   one-hop reach       requirements one EQUIVALENT_TO hop from a direct one, minus the direct ones
//   frameworks reached  distinct frameworks over direct + one-hop requirements
// Ranking key (spec / oracle):  direct requirements DESC, frameworks reached DESC,
// requirements reached (direct + one-hop) DESC, evidence id ASC.
//
// Paths are {nodes, rels}: Evidence -PROVES-> Control -SATISFIES-> Requirement [-EQUIVALENT_TO- Requirement].
MATCH (e:Evidence)
WHERE e.expires_at > date($as_of)
OPTIONAL MATCH (e)-[:PROVES]->(c:Control {adopted: true})
WITH e, collect(DISTINCT c.id) AS controls
// requirements reached directly: one path per (control, requirement)
OPTIONAL MATCH (e)-[:PROVES]->(c1:Control {adopted: true})-[:SATISFIES]->(d:Requirement)
WITH e, controls,
     collect(DISTINCT d.id) AS direct,
     collect(DISTINCT d.framework) AS fw_direct,
     collect(CASE WHEN d IS NOT NULL THEN {nodes: ['Evidence:' + e.id, 'Control:' + c1.id, 'Requirement:' + d.id],
                                            rels: ['PROVES', 'SATISFIES']} END) AS direct_paths
// one crosswalk hop further out
OPTIONAL MATCH (e)-[:PROVES]->(c2:Control {adopted: true})-[:SATISFIES]->(d2:Requirement)-[:EQUIVALENT_TO]-(h:Requirement)
WITH e, controls, direct, fw_direct, direct_paths,
     [x IN collect(DISTINCT h.id) WHERE NOT x IN direct] AS hop,
     collect(DISTINCT h.framework) AS fw_hop,
     collect(CASE WHEN h IS NOT NULL AND NOT h.id IN direct
                  THEN {nodes: ['Evidence:' + e.id, 'Control:' + c2.id, 'Requirement:' + d2.id, 'Requirement:' + h.id],
                        rels: ['PROVES', 'SATISFIES', 'EQUIVALENT_TO']} END) AS hop_paths
WITH e, controls, direct, hop, fw_direct, direct_paths, hop_paths,
     fw_direct + [f IN fw_hop WHERE NOT f IN fw_direct] AS fw_all
RETURN e.id AS evidence,
       toString(e.expires_at) AS expires_at,
       controls,
       direct AS direct_requirements,
       size(direct) AS direct_count,
       hop AS one_hop_requirements,
       size(direct) + size(hop) AS reach_count,
       fw_direct AS frameworks_direct,
       fw_all AS frameworks_reached,
       size(fw_all) AS framework_count,
       direct_paths AS paths_direct,
       hop_paths AS paths_one_hop
ORDER BY direct_count DESC, framework_count DESC, reach_count DESC, e.id ASC
