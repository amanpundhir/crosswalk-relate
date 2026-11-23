// Q5 helper: the family of each candidate requirement (used by the graph re-rank).
//   $ids  list of requirement ids
MATCH (r:Requirement)-[:PART_OF]->(f:Family)
WHERE r.id IN $ids
RETURN r.id AS id, f.id AS family
ORDER BY id
