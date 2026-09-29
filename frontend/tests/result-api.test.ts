import { afterEach, describe, expect, it, vi } from 'vitest';

import { getCurrentUser, loadAuthorizedResult, parseResultManifest, requestResultArchive } from '../src/api/result-api';
import type { ResultManifest } from '../src/api/result-types';

afterEach(() => vi.unstubAllGlobals());

describe('Result API boundary', () => {
  it('surfaces an expired browser session before concealed task reads', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'Authentication required' }), {
      status: 401, headers: { 'content-type': 'application/json' },
    })));
    await expect(getCurrentUser()).rejects.toMatchObject({ status: 401 });
    expect(fetch).toHaveBeenCalledWith('/compute/api/auth/me', expect.objectContaining({ credentials: 'same-origin' }));
  });

  it('stops result reconstruction after the expired-session probe', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: 'Authentication required' }), { status: 401 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(loadAuthorizedResult('a'.repeat(32))).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/compute/api/auth/me', expect.anything());
  });

  it('uses the server-sanitized status display name for a finished result', async () => {
    const taskId = 'a'.repeat(32), responses = [
      { id: 1, username: 'owner', email: 'owner@example.test', is_admin: false },
      { task_id: taskId, task_type: 'alphafold3', display_name: 'safe model.cif', status: 'finished', terminal: true,
        status_url: `/compute/api/running/${taskId}`, results_url: `/compute/api/results/${taskId}`, result_available: true },
      { schema_version: 3, task_id: taskId, task_type: 'alphafold3', created_at: '2026-09-29T00:00:00Z', status: 'finished', terminal: true,
        error: null, run: {}, output_check: { state: 'passed', checks: [], problems: [] }, limitations: [], views: [], artifacts: [],
        result: { files: {} }, storyboard: null, outcome: 'SUCCESS', total_size: 0, archive: { ready: false, request_url: '/archive' } },
    ];
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(responses.shift()), { status: 200, headers: { 'content-type': 'application/json' } })));
    const result = await loadAuthorizedResult(taskId);
    expect((result as ResultManifest).filename).toBe('safe model.cif');
  });

  it('parses the server AF3 logical-file shape without inventing a path', () => {
    const manifest = parseResultManifest({
      schema_version: 3, task_id: 'a'.repeat(32), task_type: 'alphafold3', created_at: '2026-09-29T00:00:00Z',
      status: 'finished', terminal: true, error: null, run: {}, output_check: { state: 'passed', checks: [], problems: [] },
      limitations: [], views: [], artifacts: [{ path: 'seed-1/model.cif', size: 9, sha256: 'f'.repeat(64), url: '/artifact',
        media_type: 'chemical/x-mmcif', preview: 'structure', capability: 'molecular_structure', role: 'primary', confidence_encoding: 'plddt_bfactor' }],
      result: { files: { structures: [{ id: 'model', name: 'model.cif', size: 9, media_type: 'chemical/x-mmcif', role: 'primary',
        cardinality: 'one', viewer: 'structure', preview: 'structure', capability: 'molecular_structure', url: '/logical/model',
        table_url: '/logical/model/table', confidence_encoding: 'plddt_bfactor' }] } },
      storyboard: { identifier: 'alphafold3', entrypoint: 'storyboard.mjs', entrypoint_url: '/storyboard/storyboard.mjs', requires: ['structures'], optional: [] },
      outcome: 'SUCCESS', total_size: 9, archive: { ready: false, request_url: '/archive' },
    });
    const result = manifest as ResultManifest;
    expect(result.result.files.structures?.[0]).toEqual(expect.objectContaining({
      id: 'model', name: 'model.cif', url: '/logical/model', table_url: '/logical/model/table', confidence_encoding: 'plddt_bfactor',
    }));
    expect('path' in (result.result.files.structures?.[0] || {})).toBe(false);
  });

  it('preserves the sanitized terminal task error', () => {
    expect(parseResultManifest({
      task_id: 'a'.repeat(32), task_type: 'example', display_name: 'result', status: 'failed', terminal: true,
      result_available: false, status_url: '/status', results_url: '/result', error: 'Runner stopped safely',
    })).toEqual(expect.objectContaining({ status: 'failed', error: 'Runner stopped safely' }));
  });

  it('mints an in-memory bearer token for the archive mutation', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => new Response(JSON.stringify(
      url.endsWith('/auth/token') ? { token: 'ephemeral' } : { ready: false },
    ), { status: 200, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    await requestResultArchive('/compute/api/results/task/archive');
    expect(fetchMock).toHaveBeenNthCalledWith(1, '/compute/api/auth/token', expect.objectContaining({ credentials: 'same-origin' }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/compute/api/results/task/archive', expect.objectContaining({
      method: 'POST', credentials: 'same-origin', headers: expect.any(Headers),
    }));
    expect((fetchMock.mock.calls[1]?.[1]?.headers as Headers).get('Authorization')).toBe('Bearer ephemeral');
  });
});
