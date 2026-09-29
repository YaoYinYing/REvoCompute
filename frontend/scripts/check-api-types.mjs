import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const temporary = await mkdtemp(resolve(tmpdir(), 'revocompute-openapi-'));
const generated = resolve(temporary, 'schema.generated.ts');

try {
  const result = spawnSync(
    process.env.OPENAPI_TYPESCRIPT_BIN || resolve(root, 'node_modules/.bin/openapi-typescript'),
    [resolve(root, '../revocompute/static/openapi.json'), '--output', generated],
    { encoding: 'utf8' },
  );
  if (result.status !== 0) {
    throw new Error(`OpenAPI type generation failed\n${result.error || result.stderr || result.stdout}`);
  }
  const [expected, actual] = await Promise.all([
    readFile(resolve(root, 'src/api/schema.generated.ts'), 'utf8'),
    readFile(generated, 'utf8'),
  ]);
  if (actual !== expected) {
    throw new Error('Generated API types are stale; run npm run generate:api-types');
  }
} finally {
  await rm(temporary, { recursive: true, force: true });
}
