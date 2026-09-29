import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const readJson = async path => JSON.parse(await readFile(path, 'utf8'));
const [manifest, lock] = await Promise.all([
  readJson(resolve(root, 'package.json')),
  readJson(resolve(root, 'package-lock.json')),
]);

const declared = { ...manifest.dependencies, ...manifest.devDependencies };
const lockedRoot = {
  ...lock.packages?.['']?.dependencies,
  ...lock.packages?.['']?.devDependencies,
};
if (JSON.stringify(declared) !== JSON.stringify(lockedRoot)) {
  throw new Error('Frontend package manifest and lockfile root dependencies differ');
}

for (const [name, version] of Object.entries(declared)) {
  const dependency = lock.packages?.[`node_modules/${name}`];
  if (!dependency || dependency.version !== version || dependency.link) {
    throw new Error(`Frontend lock does not contain exact registry package ${name}@${version}`);
  }
}

for (const [path, dependency] of Object.entries(lock.packages || {})) {
  if (path && !path.startsWith('node_modules/')) {
    throw new Error(`Frontend lock contains an external package path: ${path}`);
  }
  if (dependency.link || String(dependency.resolved || '').startsWith('file:')) {
    throw new Error(`Frontend lock contains a linked package: ${path}`);
  }
}
