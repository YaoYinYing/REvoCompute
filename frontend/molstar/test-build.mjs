import assert from 'node:assert/strict';
import { mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const work = await mkdtemp(resolve(tmpdir(), 'revocompute-molstar-build-'));
const output = resolve(work, 'assets');
const runBuild = (extra = {}) => spawnSync(
  process.execPath,
  [resolve(root, 'frontend/molstar/build.mjs')],
  { cwd: root, env: { ...process.env, MOLSTAR_OUTPUT_DIR: output, ...extra }, encoding: 'utf8' },
);

try {
  const success = runBuild();
  assert.equal(success.status, 0, success.stderr);
  assert.deepEqual((await readdir(output)).sort(), ['molstar.css', 'molstar.js']);
  for (const asset of ['molstar.js', 'molstar.css']) assert.ok((await stat(resolve(output, asset))).size > 0);

  await writeFile(resolve(output, 'last-known-good'), 'preserve-on-failure\n');
  const badProvenance = resolve(work, 'bad-provenance.json');
  await writeFile(badProvenance, '{"version":"not-the-installed-version"}\n');
  const provenanceFailure = runBuild({ MOLSTAR_PROVENANCE_FILE: badProvenance });
  assert.notEqual(provenanceFailure.status, 0, 'mismatched package provenance must fail the build');
  assert.equal(await readFile(resolve(output, 'last-known-good'), 'utf8'), 'preserve-on-failure\n');

  const failure = runBuild({ MOLSTAR_ENTRYPOINT: resolve(work, 'missing.ts') });
  assert.notEqual(failure.status, 0, 'a missing entry point must fail the build');
  assert.equal(await readFile(resolve(output, 'last-known-good'), 'utf8'), 'preserve-on-failure\n');
  assert.deepEqual(
    (await readdir(work)).filter((name) => name.startsWith('.assets.stage-')),
    [],
    'failed builds must remove staging output',
  );
} finally {
  await rm(work, { recursive: true, force: true });
}
