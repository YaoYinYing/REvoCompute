import { afterEach, describe, expect, it, vi } from 'vitest';
import { authorizedFetch, authorizedJson, clearSessionCredential, sessionExpiredEvent } from '../src/app/session';

afterEach(() => { clearSessionCredential(); vi.unstubAllGlobals(); });

describe('browser mutation authorization', () => {
  it('keeps the bearer token in memory and reuses it', async () => {
    const fetchMock = vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith('/token') ? { token: 'one' } : { ok: true }), { status: 200, headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    await authorizedJson('/compute/api/cancel/a', { method: 'POST' });
    await authorizedJson('/compute/api/cancel/b', { method: 'POST' });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/token'))).toHaveLength(1);
    expect(fetchMock).toHaveBeenLastCalledWith('/compute/api/cancel/b', expect.objectContaining({ credentials: 'same-origin' }));
  });

  it('refreshes once only when the server identifies a stale bearer credential', async () => {
    const responses = [
      new Response(JSON.stringify({ token: 'stale' }), { status: 200 }),
      new Response(JSON.stringify({ error: 'Bearer token required for this action' }), { status: 403 }),
      new Response(JSON.stringify({ token: 'fresh' }), { status: 200 }),
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    ];
    vi.stubGlobal('fetch', vi.fn(async () => responses.shift()!));
    await expect(authorizedJson('/compute/api/delete/a', { method: 'DELETE' })).resolves.toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledTimes(4);
  });

  it('does not replay an ordinary authorization denial', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'valid' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: 'Runner access is required' }), { status: 403 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(authorizedJson('/compute/api/post', { method: 'POST' })).rejects.toMatchObject({ status: 403 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('renews an expired bearer credential once', async () => {
    const responses = [
      new Response(JSON.stringify({ token: 'expired' }), { status: 200 }),
      new Response(JSON.stringify({ error: 'Bearer token has expired' }), { status: 403 }),
      new Response(JSON.stringify({ token: 'fresh' }), { status: 200 }),
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    ];
    vi.stubGlobal('fetch', vi.fn(async () => responses.shift()!));
    await expect(authorizedJson('/compute/api/delete/a', { method: 'DELETE' })).resolves.toEqual({ ok: true });
    expect(fetch).toHaveBeenCalledTimes(4);
  });

  it.each(['https://evil.example/delete', '//evil.example/delete', '/\\evil.example/delete'])(
    'rejects non-canonical authorized URL %s before minting a token',
    async (url) => {
      const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
      await expect(authorizedFetch(url, { method: 'POST' })).rejects.toThrow(/same-origin/);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it('announces mid-session expiry after an authorized mutation returns 401', async () => {
    const dispatchEvent = vi.fn(); vi.stubGlobal('window', { dispatchEvent });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'valid' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: 'Authentication required' }), { status: 401 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(authorizedJson('/compute/api/delete/a', { method: 'DELETE' })).rejects.toMatchObject({ status: 401 });
    expect(dispatchEvent).toHaveBeenCalledOnce();
    expect(dispatchEvent.mock.calls[0]?.[0]).toMatchObject({ type: sessionExpiredEvent });
  });
});
