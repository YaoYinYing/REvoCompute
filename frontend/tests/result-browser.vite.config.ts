import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vite';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputDirectory = process.env.REVOCOMPUTE_RESULT_TEST_DIST;
if (!outputDirectory) throw new Error('REVOCOMPUTE_RESULT_TEST_DIST is required');

export default defineConfig({
  root: frontend,
  base: '/static/app/',
  resolve: { alias: {
    '../structure/MolecularViewer': path.join(frontend, 'tests/fake-molecular-viewer.ts'),
    '../../structure/MolecularViewer': path.join(frontend, 'tests/fake-molecular-viewer.ts'),
  } },
  build: { emptyOutDir: true, outDir: outputDirectory, manifest: true },
});
