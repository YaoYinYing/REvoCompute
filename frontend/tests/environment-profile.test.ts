import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/*
 * The deployment profile is a Server fact; the browser may not invent one.
 *
 * A read that fails is not the production answer. It stays unresolved so the
 * Create Task run control is never offered on a deployment whose profile the
 * browser could not confirm, and so the next caller can retry instead of
 * inheriting a cached failure. The Server's submission refusal is unchanged.
 */

type EnvironmentModule = typeof import('../src/app/environment');

let environment: EnvironmentModule;

beforeEach(async () => {
  vi.resetModules();
  environment = await import('../src/app/environment');
});

afterEach(() => vi.unstubAllGlobals());

function response(payload: unknown, ok = true): Response {
  return { ok, json: async () => payload } as unknown as Response;
}

describe('the deployment profile read', () => {
  it('leaves a failed read unresolved instead of claiming production', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network down')));
    await expect(environment.loadEnvironment()).resolves.toBeNull();
  });

  it('leaves an error response unresolved', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ error: 'unavailable' }, false)));
    await expect(environment.loadEnvironment()).resolves.toBeNull();
  });

  it('does not cache the failure, so the retry reads again', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce(response({ version: 1, demo_mode: true, execution: 'preview_only', notice: 'Preview only' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(environment.loadEnvironment()).resolves.toBeNull();
    await expect(environment.loadEnvironment()).resolves.toMatchObject({ demo_mode: true, execution: 'preview_only' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('reports a resolved production profile unchanged', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ version: 1, demo_mode: false, execution: 'available' })));
    await expect(environment.loadEnvironment()).resolves.toEqual({ version: 1, demo_mode: false, execution: 'available' });
  });
});
