import { copyFile, mkdir, rm } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'esbuild';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const output = resolve(root, 'revocompute/static/vendor/molstar');

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await Promise.all([
  build({
    entryPoints: [resolve(root, 'frontend/molstar/index.ts')],
    outfile: resolve(output, 'molstar.js'),
    bundle: true,
    format: 'esm',
    minify: true,
    target: 'es2022',
    legalComments: 'eof',
  }),
  copyFile(
    resolve(root, 'node_modules/molstar/build/viewer/molstar.css'),
    resolve(output, 'molstar.css'),
  ),
]);
