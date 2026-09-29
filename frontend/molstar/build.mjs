import { access, copyFile, mkdir, mkdtemp, readFile, rename, rm, stat } from 'node:fs/promises';
import { basename, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { build } from 'esbuild';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const output = resolve(process.env.MOLSTAR_OUTPUT_DIR || resolve(root, 'revocompute/static/vendor/molstar'));
const entryPoint = resolve(process.env.MOLSTAR_ENTRYPOINT || resolve(root, 'frontend/molstar/index.ts'));
const provenanceFile = resolve(
  process.env.MOLSTAR_PROVENANCE_FILE || resolve(root, 'frontend/molstar/provenance.json'),
);
const readJson = async (path) => JSON.parse(await readFile(path, 'utf8'));
const [manifest, lock, installed, provenance] = await Promise.all([
  readJson(resolve(root, 'package.json')),
  readJson(resolve(root, 'package-lock.json')),
  readJson(resolve(root, 'node_modules/molstar/package.json')),
  readJson(provenanceFile),
]);
const locked = lock.packages?.['node_modules/molstar'];
const expectedRepository = 'https://github.com/molstar/molstar.git';
if (
  manifest.dependencies?.molstar !== provenance.version
  || lock.packages?.['']?.dependencies?.molstar !== provenance.version
  || locked?.version !== provenance.version
  || locked?.resolved !== provenance.tarball
  || locked?.integrity !== provenance.integrity
  || locked?.license !== provenance.license
  || installed.version !== provenance.version
  || installed.license !== provenance.license
  || installed.repository?.url !== expectedRepository
) {
  throw new Error('Mol* manifest, lockfile, installation, and provenance must describe the same exact package');
}
const outputParent = dirname(output);
await mkdir(outputParent, { recursive: true });
const staging = await mkdtemp(resolve(outputParent, `.${basename(output)}.stage-`));
const backup = resolve(outputParent, `.${basename(output)}.backup-${process.pid}`);

try {
  await Promise.all([
    build({
      entryPoints: [entryPoint],
      outfile: resolve(staging, 'molstar.js'),
      bundle: true,
      format: 'esm',
      minify: true,
      target: 'es2022',
      legalComments: 'eof',
    }),
    copyFile(
      resolve(root, 'node_modules/molstar/build/viewer/molstar.css'),
      resolve(staging, 'molstar.css'),
    ),
  ]);
  for (const asset of ['molstar.js', 'molstar.css']) {
    if ((await stat(resolve(staging, asset))).size === 0) throw new Error(`${asset} is empty`);
  }

  await rm(backup, { recursive: true, force: true });
  let hadPreviousOutput = true;
  try { await access(output); } catch { hadPreviousOutput = false; }
  if (hadPreviousOutput) await rename(output, backup);
  try {
    await rename(staging, output);
  } catch (error) {
    if (hadPreviousOutput) await rename(backup, output);
    throw error;
  }
  await rm(backup, { recursive: true, force: true });
} finally {
  await rm(staging, { recursive: true, force: true });
}
