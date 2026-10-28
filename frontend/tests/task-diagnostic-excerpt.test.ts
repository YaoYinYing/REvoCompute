import { afterEach, expect, it, vi } from 'vitest';
import { getTaskDiagnosticExcerpt, MAX_DIAGNOSTIC_EXCERPT_BYTES } from '../src/api/app-api';

afterEach(() => vi.unstubAllGlobals());

it('refuses a non-server excerpt path before issuing a request', async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  for (const url of ['https://evil.example/x', '//evil.example/x', '/compute\\api', 'relative']) {
    await expect(getTaskDiagnosticExcerpt(url)).rejects.toThrow('same-origin');
  }
  expect(fetchMock).not.toHaveBeenCalled();
});

it('returns the server-bounded excerpt and refuses one past the bound', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('safe line\n')));
  await expect(getTaskDiagnosticExcerpt('/compute/api/tasks/a/diagnostics/stderr')).resolves.toBe('safe line\n');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('x'.repeat(MAX_DIAGNOSTIC_EXCERPT_BYTES + 1))));
  await expect(getTaskDiagnosticExcerpt('/compute/api/tasks/a/diagnostics/stderr')).rejects.toThrow('server bound');
});

it('reports an authorization refusal from the excerpt route', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: 'Not found' }), {
    status: 404, headers: { 'Content-Type': 'application/json' },
  })));
  await expect(getTaskDiagnosticExcerpt('/compute/api/tasks/a/diagnostics/stderr')).rejects.toMatchObject({ status: 404 });
});
