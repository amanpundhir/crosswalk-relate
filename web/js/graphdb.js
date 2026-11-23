// A thin, DOM-free wrapper around the Relate WASM database.
// Shared by the browser app (js/app.js) and the Node check (check.mjs), so both run the same code
// and the same query text from queries/*.cypher.

export class GraphDb {
  /** @param {new () => any} RelateDb  the class exported by vendor/relate/relate.js (after init) */
  constructor(RelateDb) {
    this.RelateDb = RelateDb;
    this.db = new RelateDb();
    this.statements = [];
    this.queries = {};
    this.loadedMs = 0;
  }

  /** graph.cypher text -> statements (one per line; blank lines and // comments skipped). */
  setScript(text) {
    this.statements = text
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('//'))
      .map((l) => l.replace(/;$/, ''));
  }

  setQueries(map) {
    this.queries = map;
  }

  /** Run one Cypher statement; returns {columns, rows, stats}. Throws on an engine error. */
  run(cypher, params = null) {
    const wire = JSON.parse(this.db.execute(cypher, params ? JSON.stringify(params) : null));
    if (wire.error) throw new Error(wire.error);
    return { columns: wire.columns, rows: wire.rows, stats: wire.stats };
  }

  /** Run a named query from queries/<name>.cypher; returns the rows. */
  q(name, params = null) {
    const text = this.queries[name];
    if (!text) throw new Error(`unknown query ${name}`);
    return this.run(text, params).rows;
  }

  /** (Re)build the graph in memory from graph.cypher. Everything done before is discarded. */
  load(onProgress) {
    const t0 = performance.now();
    this.db.reset();
    const n = this.statements.length;
    this.statements.forEach((s, i) => {
      this.run(s);
      if (onProgress) onProgress(i + 1, n);
    });
    this.loadedMs = Math.round(performance.now() - t0);
    return this.loadedMs;
  }
}
