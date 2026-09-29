import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vite';

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const outputDirectory = process.env.REVOCOMPUTE_SCIENTIFIC_TEST_DIST;
if (!outputDirectory) throw new Error('REVOCOMPUTE_SCIENTIFIC_TEST_DIST is required');

export default defineConfig({
  build: {
    emptyOutDir: true,
    outDir: outputDirectory,
    lib: { entry: path.join(testDirectory, 'scientific-browser-entry.ts'), formats: ['iife'], name: 'REvoComputeScientificTest' },
    rollupOptions: { output: { entryFileNames: 'scientific.js', assetFileNames: 'scientific.[ext]' } },
  },
});
