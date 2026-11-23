// check_path: does this exact path exist in the graph, and is it currently valid?
// This is the claim checker's re-run of a cited path (see src/crosswalk/paths.py for the format).
//
// Parameters:
//   $nodes   list of 'Label:id' references, e.g.
//            ['Requirement:800-171:03.05.03', 'Control:CTRL-REAP-6', 'Evidence:EV-044']
//            (the id may itself contain colons: only the first colon splits label from id)
//   $rels    list of relationship tokens, one fewer than $nodes: 'TYPE' if walked along the stored
//            direction from the left node to the right node, 'TYPE<-' if walked against it, e.g.
//            ['SATISFIES<-', 'PROVES<-'].  EQUIVALENT_TO is symmetric: direction is ignored.
//   $as_of   'YYYY-MM-DD' (Meta.as_of; never the system clock)
//
// EXISTS: every hop is present with the right label, id, type and direction.
// VALID : it exists and, at $as_of,
//           * every SATISFIES hop is approved (approved_by is set),
//           * every Control on the path is adopted,
//           * every Evidence on the path has expires_at > $as_of,
//           * every Proposal on the path (a *proposed path*: Requirement<-TARGET-Proposal-ABOUT->Control)
//             is approved: a pending or rejected proposal is "proposed, not approved".
// A path that contains a Decision node (Decision-ON->Proposal-ABOUT->Control, ...) is a receipt that a
// decision was recorded, not a claim that the mapping holds: its Proposal / Control / Evidence nodes are
// then only checked for existence.
// (Absence hops, 'NO_OWNS<-', are verified by check_absence.cypher; see queries.check_path.)
// One row comes back: exists, valid and `problems`, human-readable reasons (empty when valid).
UNWIND range(0, size($rels) - 1) AS i
WITH i,
     $nodes[i] AS a_ref,
     $nodes[i + 1] AS b_ref,
     $rels[i] AS token
WITH i, a_ref, b_ref, token,
     split(a_ref, ':')[0] AS a_label,
     substring(a_ref, size(split(a_ref, ':')[0]) + 1) AS a_id,
     split(b_ref, ':')[0] AS b_label,
     substring(b_ref, size(split(b_ref, ':')[0]) + 1) AS b_id,
     token ENDS WITH '<-' AS reversed,
     CASE WHEN token ENDS WITH '<-' THEN substring(token, 0, size(token) - 2) ELSE token END AS rel_type
OPTIONAL MATCH (a)-[r]-(b)
WHERE a.id = a_id AND a_label IN labels(a)
  AND b.id = b_id AND b_label IN labels(b)
  AND type(r) = rel_type
  AND (rel_type = 'EQUIVALENT_TO' OR (NOT reversed AND startNode(r) = a) OR (reversed AND endNode(r) = a))
WITH i, a_ref, b_ref, token, r, a, b, rel_type,
     [x IN [
        CASE WHEN r IS NOT NULL AND rel_type = 'SATISFIES' AND r.approved_by IS NULL
             THEN 'mapping ' + a_ref + ' - ' + b_ref + ' is not approved' END,
        CASE WHEN r IS NOT NULL AND NOT any(n IN $nodes WHERE n STARTS WITH 'Decision:') AND 'Control' IN labels(a) AND coalesce(a.adopted, false) = false
             THEN a_ref + ' is not adopted' END,
        CASE WHEN r IS NOT NULL AND NOT any(n IN $nodes WHERE n STARTS WITH 'Decision:') AND 'Control' IN labels(b) AND coalesce(b.adopted, false) = false
             THEN b_ref + ' is not adopted' END,
        CASE WHEN r IS NOT NULL AND NOT any(n IN $nodes WHERE n STARTS WITH 'Decision:') AND 'Evidence' IN labels(a) AND NOT a.expires_at > date($as_of)
             THEN a_ref + ' expired ' + toString(a.expires_at) END,
        CASE WHEN r IS NOT NULL AND NOT any(n IN $nodes WHERE n STARTS WITH 'Decision:') AND 'Evidence' IN labels(b) AND NOT b.expires_at > date($as_of)
             THEN b_ref + ' expired ' + toString(b.expires_at) END,
        CASE WHEN r IS NOT NULL AND NOT any(n IN $nodes WHERE n STARTS WITH 'Decision:') AND 'Proposal' IN labels(a) AND coalesce(a.status, 'pending') <> 'approved'
             THEN 'mapping ' + coalesce([(a)-[:ABOUT]->(c1:Control) | c1.id][0], '?') + ' -> '
                  + coalesce([(a)-[:TARGET]->(t1:Requirement) | t1.id][0], '?')
                  + CASE WHEN a.status = 'rejected' THEN ' was rejected (' ELSE ' is proposed (' END
                  + a.id + '), not approved' END,
        CASE WHEN r IS NOT NULL AND NOT any(n IN $nodes WHERE n STARTS WITH 'Decision:') AND 'Proposal' IN labels(b) AND coalesce(b.status, 'pending') <> 'approved'
             THEN 'mapping ' + coalesce([(b)-[:ABOUT]->(c2:Control) | c2.id][0], '?') + ' -> '
                  + coalesce([(b)-[:TARGET]->(t2:Requirement) | t2.id][0], '?')
                  + CASE WHEN b.status = 'rejected' THEN ' was rejected (' ELSE ' is proposed (' END
                  + b.id + '), not approved' END
      ] WHERE x IS NOT NULL] AS invalid,
     CASE WHEN r IS NULL THEN ['no ' + token + ' relationship from ' + a_ref + ' to ' + b_ref] ELSE [] END AS missing
WITH i,
     max(CASE WHEN r IS NOT NULL THEN 1 ELSE 0 END) AS found,
     collect(missing) AS missing_lists,
     collect(invalid) AS invalid_lists
WITH collect({found: found,
              missing: reduce(acc = [], m IN missing_lists | acc + m),
              invalid: reduce(acc = [], m IN invalid_lists | acc + m)}) AS steps
RETURN size(steps) = size($rels) AND all(s IN steps WHERE s.found = 1) AS exists,
       size(steps) = size($rels)
         AND all(s IN steps WHERE s.found = 1 AND size(s.invalid) = 0) AS valid,
       reduce(acc = [], s IN steps | acc + s.missing + s.invalid) AS problems
