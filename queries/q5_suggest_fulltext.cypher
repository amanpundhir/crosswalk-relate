// Q5 (full text): mapping candidates for a control, by BM25 keyword match on title + text.
// A Relate full-text SEARCH needs a LIMIT and cannot filter by framework inside the index, so it
// pulls a pool (default: every requirement) and the framework filter is applied afterwards.
// $q must already be sanitised (see crosswalk.suggest.sanitise_query): no AND/OR/NOT, wildcards, ~ or ^.
//
// Parameters:
//   $q          sanitised query text
//   $framework  '800-53' | '800-171' | 'CSF'
//   $k          number of candidates to return
//   $ft_pool    how many raw hits to pull before the framework filter (>= number of requirements)
MATCH (r:Requirement)
  SEARCH r IN (FULLTEXT INDEX requirement_text_ft FOR $q LIMIT $ft_pool)
  SCORE AS score
WHERE r.framework = $framework
RETURN r.id AS id, r.title AS title, score
ORDER BY score DESC, id
LIMIT $k
