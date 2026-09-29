import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const readJson = async path => JSON.parse(await readFile(path, 'utf8'));
const [manifest, lock, installed, provenance] = await Promise.all([
  readJson(resolve(root, 'package.json')),
  readJson(resolve(root, 'package-lock.json')),
  readJson(resolve(root, 'node_modules/molstar/package.json')),
  readJson(resolve(root, 'provenance/molstar.json')),
]);
const locked = lock.packages?.['node_modules/molstar'];

const actual = {
  manifestVersion: manifest.dependencies?.molstar,
  lockRootVersion: lock.packages?.['']?.dependencies?.molstar,
  lockedVersion: locked?.version,
  lockedTarball: locked?.resolved,
  lockedIntegrity: locked?.integrity,
  lockedLicense: locked?.license,
  installedVersion: installed.version,
  installedLicense: installed.license,
  installedRepository: installed.repository?.url,
};
const expected = {
  manifestVersion: provenance.version,
  lockRootVersion: provenance.version,
  lockedVersion: provenance.version,
  lockedTarball: provenance.tarball,
  lockedIntegrity: provenance.integrity,
  lockedLicense: provenance.license,
  installedVersion: provenance.version,
  installedLicense: provenance.license,
  installedRepository: provenance.repository,
};

if (JSON.stringify(actual) !== JSON.stringify(expected)) {
  throw new Error(`Mol* provenance mismatch\nexpected ${JSON.stringify(expected)}\nactual   ${JSON.stringify(actual)}`);
}
