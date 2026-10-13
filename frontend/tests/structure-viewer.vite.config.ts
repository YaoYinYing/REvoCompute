// Copyright (c) 2026 The REvoDesign Developers.
// Distributed under the terms of the GNU General Public License v3.0.
// SPDX-License-Identifier: GPL-3.0-only
//
// Builds the real ``MolecularViewer`` into a browser-loadable bundle for the
// advanced-controls contract. The shipped chunk cannot be loaded on a page of
// its own: it shares the application chunk, whose bootstrap requires the app
// root. Building the viewer's own entry gives the mode contract a page that
// mounts the viewer and nothing else. Development mode is deliberate: the case
// reports the console and page errors a reader would meet, and React's
// development build is what raises them (a prop-type mismatch is silent in
// production).
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vite';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outputDirectory = process.env.REVOCOMPUTE_STRUCTURE_TEST_DIST;
const cacheDirectory = process.env.REVOCOMPUTE_STRUCTURE_TEST_BUILD;
if (!outputDirectory || !cacheDirectory) throw new Error('REVOCOMPUTE_STRUCTURE_TEST_DIST and REVOCOMPUTE_STRUCTURE_TEST_BUILD are required');

export default defineConfig({
  root: frontend,
  mode: 'development',
  cacheDir: cacheDirectory,
  define: { 'process.env.NODE_ENV': '"development"' },
  build: {
    emptyOutDir: true,
    outDir: outputDirectory,
    minify: false,
    lib: { entry: path.join(frontend, 'tests/structure-viewer-browser-entry.ts'), formats: ['iife'], name: 'REvoComputeStructureTest' },
    rollupOptions: { output: { entryFileNames: 'structure-viewer.js', assetFileNames: 'structure-viewer.[ext]' } },
  },
});
