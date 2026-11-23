// Copies the pinned browser dependencies from node_modules into vendor/ so the site needs no CDN.
//   cd web && npm ci && npm run vendor
// Run it again only after changing a pinned version in package.json.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const nm = path.join(root, 'node_modules');
const copies = [
  ['@relate/relate-wasm/relate.js', 'vendor/relate/relate.js'],
  ['@relate/relate-wasm/relate_bg.wasm', 'vendor/relate/relate_bg.wasm'],
  ['@relate/relate-wasm/trap.js', 'vendor/relate/trap.js'],
  ['@relate/relate-wasm/snippets/relate-wasm-dd0c6225f894802b/js/opfs.js', 'vendor/relate/snippets/relate-wasm-dd0c6225f894802b/js/opfs.js'],
  ['@relate/relate-wasm/package.json', 'vendor/relate/PACKAGE.json'],
  ['cytoscape/dist/cytoscape.min.js', 'vendor/cytoscape/cytoscape.min.js'],
  ['cytoscape/LICENSE', 'vendor/cytoscape/LICENSE'],
];
for (const [from, to] of copies) {
  const dst = path.join(root, to);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.copyFileSync(path.join(nm, from), dst);
  console.log(`${from} -> ${to}`);
}
