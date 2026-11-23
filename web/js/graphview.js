// Graph tab: Cytoscape.js canvas fed by Cypher neighbour queries against the in-memory Relate graph.
import { splitRef, shortId } from './analysis.js';

const LABELS = new Set(['Framework', 'Family', 'Requirement', 'Control', 'Evidence', 'Person', 'System',
  'Policy', 'Audit', 'Agent', 'Proposal', 'Decision', 'TrackerRow']);

// colour + shape per label (shape differs too, so the meaning does not rest on colour alone)
const STYLE = {
  Requirement: { color: '#3b6fd8', shape: 'ellipse' },
  Control: { color: '#1f9d6b', shape: 'round-rectangle' },
  Evidence: { color: '#d9822b', shape: 'diamond' },
  Person: { color: '#8e5bd0', shape: 'ellipse' },
  System: { color: '#6b7785', shape: 'rectangle' },
  Policy: { color: '#8a6d3b', shape: 'round-tag' },
  Audit: { color: '#c2467f', shape: 'hexagon' },
  Proposal: { color: '#c9a227', shape: 'octagon' },
  Decision: { color: '#7a8f2b', shape: 'pentagon' },
  TrackerRow: { color: '#9a8c98', shape: 'tag' },
  Agent: { color: '#2a9bb0', shape: 'ellipse' },
  Framework: { color: '#222a36', shape: 'barrel' },
  Family: { color: '#5a6b7f', shape: 'round-rectangle' },
};
const STATE = { fail: '#d6372c', warn: '#d49a00', ok: '#1f9d6b' };

export const LEGEND = Object.entries(STYLE).map(([label, s]) => ({ label, ...s }));

export function caption(label, id) {
  return label === 'Requirement' || label === 'Family' ? shortId(id) : id;
}

export class GraphView {
  constructor(container, g, { onSelect } = {}) {
    this.g = g;
    this.onSelect = onSelect || (() => {});
    this.cy = window.cytoscape({
      container,
      wheelSensitivity: 0.25,
      minZoom: 0.15,
      maxZoom: 3,
      style: this.#style(),
    });
    this.cy.on('tap', 'node', (e) => this.select(e.target.id(), { expand: true }));
    this.cy.on('tap', (e) => { if (e.target === this.cy) this.#deselect(); });
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => this.cy.style(this.#style()));
  }

  #style() {
    const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const text = dark ? '#e6e9ed' : '#1b1f24';
    const edge = dark ? '#5d6875' : '#9aa5b1';
    const halo = dark ? '#0f1318' : '#ffffff';
    const base = [
      { selector: 'node', style: {
        'background-color': '#6b7785', label: 'data(caption)', color: text, 'font-size': 11,
        'text-valign': 'bottom', 'text-margin-y': 4, 'text-wrap': 'ellipsis', 'text-max-width': 110,
        'text-outline-color': halo, 'text-outline-width': 2, width: 26, height: 26,
        'border-width': 2, 'border-color': halo,
      } },
      { selector: 'edge', style: {
        width: 1.5, 'line-color': edge, 'target-arrow-color': edge, 'target-arrow-shape': 'triangle',
        'curve-style': 'bezier', label: 'data(type)', 'font-size': 8, color: edge, 'text-rotation': 'autorotate',
        'text-outline-color': halo, 'text-outline-width': 2, 'arrow-scale': 0.9,
      } },
      { selector: 'node:selected', style: { 'border-color': text, 'border-width': 3 } },
      { selector: '.fail', style: { 'line-color': STATE.fail, 'target-arrow-color': STATE.fail, width: 3, color: STATE.fail } },
      { selector: 'node.fail', style: { 'border-color': STATE.fail, 'border-width': 4 } },
      { selector: '.warn', style: { 'line-color': STATE.warn, 'target-arrow-color': STATE.warn, width: 3, color: STATE.warn } },
      { selector: 'node.warn', style: { 'border-color': STATE.warn, 'border-width': 4 } },
      { selector: '.ok', style: { 'line-color': STATE.ok, 'target-arrow-color': STATE.ok, width: 3, color: STATE.ok } },
      { selector: 'node.ok', style: { 'border-color': STATE.ok, 'border-width': 4 } },
    ];
    for (const [label, s] of Object.entries(STYLE)) {
      base.push({ selector: `node[label = "${label}"]`, style: { 'background-color': s.color, shape: s.shape } });
    }
    return base;
  }

  clear() {
    this.cy.elements().remove();
    this.#deselect();
  }

  #deselect() {
    this.onSelect(null);
  }

  #addNode(label, id) {
    const key = `${label}:${id}`;
    if (this.cy.getElementById(key).empty()) {
      this.cy.add({ group: 'nodes', data: { id: key, label, nid: id, caption: caption(label, id) } });
    }
    return key;
  }

  #addEdge(from, to, type) {
    const eid = `${from}|${type}|${to}`;
    if (this.cy.getElementById(eid).empty()) {
      this.cy.add({ group: 'edges', data: { id: eid, source: from, target: to, type } });
    }
    return eid;
  }

  /** Fit everything in view, but never zoom in so far that a two-node path fills the canvas. */
  #fit() {
    this.cy.fit(undefined, 40);
    if (this.cy.zoom() > 1.15) {
      this.cy.zoom(1.15);
      this.cy.center();
    }
  }

  #layout() {
    this.cy.layout({
      name: 'cose', animate: false, fit: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 70,
      randomize: !this.cy.nodes().some((n) => n.position().x !== 0),
    }).run();
    this.#fit();
  }

  /** Details of one node (all stored properties) from the graph. */
  details(key) {
    const { label, id } = splitRef(key);
    if (!LABELS.has(label)) return null;
    const row = this.g.run(`MATCH (n:${label} {id: $id}) RETURN properties(n) AS p`, { id }).rows[0];
    return row ? { label, id, props: row.p } : null;
  }

  /** Neighbours of a node, added to the canvas (capped per direction so the picture stays readable). */
  expand(key, cap = 40) {
    const { label, id } = splitRef(key);
    if (!LABELS.has(label)) return { shown: 0, total: 0 };
    let shown = 0;
    let total = 0;
    for (const dir of ['out', 'in']) {
      const pat = dir === 'out' ? `(n)-[r]->(m)` : `(n)<-[r]-(m)`;
      const rows = this.g.run(
        `MATCH (n:${label} {id: $id}) MATCH ${pat} RETURN type(r) AS type, labels(m)[0] AS label, m.id AS id LIMIT ${cap}`,
        { id },
      ).rows;
      total += this.g.run(`MATCH (n:${label} {id: $id}) MATCH ${pat} RETURN count(r) AS c`, { id }).rows[0].c;
      for (const r of rows) {
        const other = this.#addNode(r.label, r.id);
        if (dir === 'out') this.#addEdge(key, other, r.type); else this.#addEdge(other, key, r.type);
        shown++;
      }
    }
    return { shown, total };
  }

  /** Show one node and its neighbours. */
  select(key, { expand = true, layout = true } = {}) {
    const { label, id } = splitRef(key);
    const k = this.#addNode(label, id);
    let info = { shown: 0, total: 0 };
    if (expand) info = this.expand(k);
    if (layout) this.#layout();
    this.cy.nodes().unselect();
    this.cy.getElementById(k).select();
    this.onSelect(this.details(k), info);
  }

  /**
   * Draw cited paths ([{nodes:['Label:id',..], rels:['SATISFIES<-',..], state:'ok'|'warn'|'fail', bad:[ids]}])
   * with each path coloured by its verdict; ids in `bad` get a coloured outline.
   */
  showPaths(paths) {
    this.clear();
    let root = null;
    for (const p of paths) {
      const keys = p.nodes.map((n) => {
        const { label, id } = splitRef(n);
        return this.#addNode(label, id);
      });
      root ||= keys[0];
      p.rels.forEach((tok, i) => {
        const reversed = tok.endsWith('<-');
        const type = reversed ? tok.slice(0, -2) : tok;
        const [a, b] = reversed ? [keys[i + 1], keys[i]] : [keys[i], keys[i + 1]];
        this.cy.getElementById(this.#addEdge(a, b, type)).addClass(p.state || 'ok');
      });
      const bad = new Set(p.bad || []);
      for (const k of keys) {
        if (bad.has(splitRef(k).id)) this.cy.getElementById(k).addClass(p.state || 'ok');
      }
    }
    this.cy.layout({ name: 'breadthfirst', directed: false, animate: false, fit: false, padding: 40,
      spacingFactor: 1.5, direction: 'rightward', roots: root ? [root] : undefined }).run();
    this.#fit();
    this.onSelect(null);
  }

  resize() {
    this.cy.resize();
    this.#fit();
  }

  get empty() {
    return this.cy.elements().empty();
  }
}
