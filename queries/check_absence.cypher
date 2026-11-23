// check_absence: the last hop of an ABSENCE receipt, e.g.  Control:CTRL-X | NO_OWNS<- | Person:*
// ("control CTRL-X exists, is adopted, and nobody owns it").  See src/crosswalk/paths.py.
//
// Parameters:
//   $label        label of the node the absence is about ('Control')
//   $id           its id
//   $other_label  label of the node that must NOT be related to it ('Person')
//   $other_id     its id, or '*' for any node of that label
//   $rel          relationship TYPE that must not exist ('OWNS')
//   $reversed     false: (a)-[:TYPE]->(b) must not exist;  true: (a)<-[:TYPE]-(b) must not exist
//
// No row = the node itself does not exist.  Otherwise one row: the node's `adopted` flag (null when it
// is not a Control) and `present`, the ids of the related nodes that DO exist (the absence holds when
// `present` is empty).
MATCH (a)
WHERE a.id = $id AND $label IN labels(a)
OPTIONAL MATCH (a)-[r]-(b)
WHERE type(r) = $rel
  AND $other_label IN labels(b)
  AND ($other_id = '*' OR b.id = $other_id)
  AND ((NOT $reversed AND startNode(r) = a) OR ($reversed AND endNode(r) = a))
RETURN a.adopted AS adopted, collect(b.id) AS present
