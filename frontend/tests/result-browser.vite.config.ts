import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vite';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputDirectory = process.env.REVOCOMPUTE_RESULT_TEST_DIST;
if (!outputDirectory) throw new Error('REVOCOMPUTE_RESULT_TEST_DIST is required');

export default defineConfig({
  root: frontend,
  base: '/static/app/',
  // The browser acceptance bundle carries a deterministic identity so the
  // Version page can compare it with the fixture server. It matches
  // `frontend_fixtures.builders.VERSION_SHA` by default; a case may supply a
  // different commit to drive the mixed-deployment diagnostic.
  define: {
    __REVOCOMPUTE_BUILD__: JSON.stringify({
      gitSha: process.env.REVOCOMPUTE_TEST_BUILD_GIT_SHA || '2890609' + '0'.repeat(33),
      builtAt: '2026-11-12T00:00:00Z',
      baseVersion: '0.1.0',
    }),
  },
  resolve: { alias: {
    '../structure/MolecularViewer': path.join(frontend, 'tests/fake-molecular-viewer.ts'),
    '../../structure/MolecularViewer': path.join(frontend, 'tests/fake-molecular-viewer.ts'),
  } },
  build: { emptyOutDir: true, outDir: outputDirectory, manifest: true },
});
