// Q5 (hybrid): vector + full-text candidates fused with weighted reciprocal-rank fusion (WRRF), done by
// hand: each method returns its ranked ids, and   score = w_vec/(c + rank_vec) + w_ft/(c + rank_ft).
// A candidate found by only one method simply gets 0 from the other.  Ties break on id, so the output
// is deterministic.
//
// Parameters:
//   $v          the control's embedding (LIST<FLOAT>)
//   $q          sanitised full-text query
//   $framework  '800-53' | '800-171' | 'CSF'
//   $k          number of fused candidates to return
//   $pool       candidates taken from each method before fusion
//   $ft_pool    raw full-text hits to pull before the framework filter
//   $w_vec      weight of the vector ranking          (0.7)
//   $w_ft       weight of the full-text ranking       (0.3)
//   $rrf_c      the RRF constant                      (60)
CALL () {
  MATCH (r:Requirement)
    SEARCH r IN (VECTOR INDEX requirement_embedding FOR $v WHERE r.framework = $framework LIMIT $pool)
    SCORE AS s
  WITH r, s ORDER BY s DESC, r.id
  WITH collect(r.id) AS ids, collect(s) AS scores
  UNWIND range(0, size(ids) - 1) AS i
  RETURN ids[i] AS id, 'vector' AS src, i + 1 AS rank, scores[i] AS raw
  UNION ALL
  MATCH (r:Requirement)
    SEARCH r IN (FULLTEXT INDEX requirement_text_ft FOR $q LIMIT $ft_pool)
    SCORE AS s
  WHERE r.framework = $framework
  WITH r, s ORDER BY s DESC, r.id
  WITH collect(r.id)[0..$pool] AS ids, collect(s)[0..$pool] AS scores
  UNWIND range(0, size(ids) - 1) AS i
  RETURN ids[i] AS id, 'fulltext' AS src, i + 1 AS rank, scores[i] AS raw
}
WITH id,
     sum(CASE src WHEN 'vector' THEN $w_vec / ($rrf_c + rank) ELSE 0.0 END) AS vector_part,
     sum(CASE src WHEN 'fulltext' THEN $w_ft / ($rrf_c + rank) ELSE 0.0 END) AS fulltext_part,
     max(CASE src WHEN 'vector' THEN rank END) AS vector_rank,
     max(CASE src WHEN 'fulltext' THEN rank END) AS fulltext_rank,
     max(CASE src WHEN 'vector' THEN raw END) AS vector_score,
     max(CASE src WHEN 'fulltext' THEN raw END) AS fulltext_score
MATCH (r:Requirement {id: id})
RETURN id, r.title AS title, vector_part + fulltext_part AS score,
       vector_part, fulltext_part, vector_rank, fulltext_rank, vector_score, fulltext_score
ORDER BY score DESC, id
LIMIT $k
