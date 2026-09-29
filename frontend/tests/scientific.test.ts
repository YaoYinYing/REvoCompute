import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ResultArtifact } from '../src/api/result-types';
import { loadNumericProjection, loadProjection } from '../src/features/results/scientific';

const artifact = { path: 'matrix.npy', size: 100, sha256: 'a'.repeat(64), url: '/file', ndarray_url: '/projection',
  media_type: 'application/x-npy', preview: null, capability: 'plot', role: 'evidence' } satisfies ResultArtifact;

afterEach(() => vi.unstubAllGlobals());

describe('loadNumericProjection', () => {
  it('loads one server-bounded projection while preserving storage-agnostic shape', async () => {
    const payload = { kind: 'numeric', dtype: '<f4', shape: [2, 2], key: null, total_elements: 4, data: [1, 2, 3, 4] };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })));
    await expect(loadNumericProjection(artifact, { maxElements: 4 })).resolves.toEqual({ dtype: '<f4', shape: [2, 2], key: null, totalElements: 4, values: [1, 2, 3, 4] });
    expect(fetch).toHaveBeenCalledWith('/projection?max_elements=4', expect.objectContaining({ credentials: 'same-origin' }));
  });

  it('accepts numeric scalars and bounded categorical vectors', async () => {
    const payloads = [
      { kind: 'numeric', dtype: 'float64', shape: [], key: null, total_elements: 1, data: [0.91] },
      { kind: 'categorical', dtype: 'string', shape: [2], key: 'chain_ids', total_elements: 2, data: ['A', 'B'] },
    ];
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(payloads.shift()), { status: 200 })));
    await expect(loadNumericProjection(artifact)).resolves.toMatchObject({ shape: [], values: [0.91] });
    await expect(loadProjection(artifact, { kind: 'categorical', key: 'chain_ids' })).resolves.toMatchObject({ shape: [2], values: ['A', 'B'] });
  });

  it('forwards abort without retrying or loading an unbounded response', async () => {
    const controller = new AbortController(); controller.abort();
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => { if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError'); return new Response(); }));
    await expect(loadNumericProjection(artifact, { signal: controller.signal })).rejects.toHaveProperty('name', 'AbortError');
  });
});
