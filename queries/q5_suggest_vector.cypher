// Q5 (vector): mapping candidates for a control, by embedding similarity.
// Exact cosine search over Requirement.embedding, pre-filtered to one framework by the index's
// WITH [framework] clause (so the LIMIT is applied after the framework filter).
//
// Parameters:
//   $v          the control's 384-d embedding (LIST<FLOAT>)
//   $framework  '800-53' | '800-171' | 'CSF'
//   $k          number of candidates to return
MATCH (r:Requirement)
  SEARCH r IN (VECTOR INDEX requirement_embedding FOR $v WHERE r.framework = $framework LIMIT $k)
  SCORE AS score
RETURN r.id AS id, r.title AS title, score
ORDER BY score DESC, id
