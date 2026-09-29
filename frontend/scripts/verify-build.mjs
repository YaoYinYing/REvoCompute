import { readdir, readFile, stat } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = resolve(root, 'dist');
const index = await readFile(resolve(dist, 'index.html'), 'utf8');
const manifest = JSON.parse(await readFile(resolve(dist, '.vite/manifest.json'), 'utf8'));
const assets = await readdir(resolve(dist, 'assets'));

if (!manifest['index.html']?.isEntry) throw new Error('Vite manifest does not declare the application entry');
const resultEntry = manifest['src/features/results/index.ts'];
if (!resultEntry?.dynamicImports?.includes('src/features/structure/MolecularViewer.ts')) {
  throw new Error('Result workspace does not lazy-load the MolecularViewer entry');
}
if (resultEntry.imports?.includes('src/features/structure/MolecularViewer.ts')) {
  throw new Error('Result workspace eagerly imports the MolecularViewer entry');
}
const molecularViewer = manifest['src/features/structure/MolecularViewer.ts'];
if (!molecularViewer?.file || !molecularViewer.isDynamicEntry) {
  throw new Error('Frontend build does not emit the lazy MolecularViewer chunk');
}
if ((await stat(resolve(dist, molecularViewer.file))).size === 0) {
  throw new Error('Frontend build emitted an empty MolecularViewer chunk');
}
if (!assets.some(name => name.endsWith('.js'))) throw new Error('Frontend build emitted no JavaScript asset');
if (!assets.some(name => name.endsWith('.css'))) throw new Error('Frontend build emitted no stylesheet asset');
if (!index.includes('/static/app/assets/')) throw new Error('Frontend entry does not use the production asset base');
for (const asset of assets) {
  if ((await stat(resolve(dist, 'assets', asset))).size === 0) throw new Error(`Frontend emitted an empty asset: ${asset}`);
}
const output = await Promise.all(assets.map(name => readFile(resolve(dist, 'assets', name), 'utf8').catch(() => '')));
if (output.some(value => /(?:cdn\.jsdelivr\.net|unpkg\.com)\/.*molstar/i.test(value))) {
  throw new Error('Frontend build contains a runtime Mol* CDN reference');
}
if (output.some(value => value.includes('/static/vendor/molstar'))) {
  throw new Error('Frontend build contains the superseded Mol* vendor path');
}
