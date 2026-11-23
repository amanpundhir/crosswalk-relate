// Q5 helper: what we know about the control a mapping is being suggested for.
//   $control  control id
MATCH (c:Control {id: $control})
OPTIONAL MATCH (c)<-[:MANDATES]-(p:Policy)
RETURN c.id AS id, c.title AS title, c.text AS text, c.context AS context, c.embedding AS embedding,
       p.id AS policy
