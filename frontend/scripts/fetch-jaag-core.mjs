/*
 * Materialize the pinned JAAG core bundle for the create-task builder.
 *
 * The bundle is Apache-2.0 third-party code and is deliberately not committed;
 * it is fetched from the immutable upstream commit and verified against the
 * pinned SHA-256 before it is written into the ignored vendor directory. The
 * REvoCompute-owned adapter that consumes it lives in src/.
 */
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const pin = JSON.parse(await readFile(resolve(root, 'provenance/jaag.json'), 'utf8'));
const target = resolve(root, pin.asset_path);
const url = `https://raw.githubusercontent.com/${pin.repository_path}/${pin.commit}/${pin.asset}`;

const digest = value => createHash('sha256').update(value).digest('hex');

try {
  const current = await readFile(target);
  if (digest(current) === pin.sha256) {
    process.stdout.write(`JAAG core ${pin.commit.slice(0, 8)} already present in ${pin.asset_path}\n`);
    process.exit(0);
  }
} catch (error) {
  if (error?.code !== 'ENOENT') throw error;
}

let response;
try {
  response = await fetch(url, { redirect: 'follow', signal: AbortSignal.timeout(60_000) });
} catch (error) {
  throw new Error(
    `Cannot fetch the pinned JAAG core from ${url}: ${error.message}. `
    + 'The create-task builder requires network access during frontend build and test.',
  );
}
if (!response.ok) {
  throw new Error(`Cannot fetch the pinned JAAG core from ${url}: HTTP ${response.status}`);
}
const body = Buffer.from(await response.arrayBuffer());
const actual = digest(body);
if (actual !== pin.sha256) {
  throw new Error(
    `Pinned JAAG core checksum mismatch: expected ${pin.sha256}, received ${actual} from ${url}`,
  );
}
await mkdir(dirname(target), { recursive: true });
const temporary = `${target}.${process.pid}.tmp`;
await writeFile(temporary, body, { mode: 0o644 });
await rename(temporary, target);
process.stdout.write(`Fetched pinned JAAG core ${pin.commit.slice(0, 8)} (${pin.license}) to ${pin.asset_path}\n`);
