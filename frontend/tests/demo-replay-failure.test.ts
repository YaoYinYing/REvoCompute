import { afterEach, describe, expect, it, vi } from 'vitest';

import { HarnessNode, installHarness } from './dom-harness';

/*
 * A replay-catalog read that fails is not an empty catalog.
 *
 * The landing used to turn any failure into "No replay scenarios are installed",
 * and the replay page had no failure state at all: a reader could not tell a
 * broken deployment from one with no curated scenarios. The failure is now
 * stated and retried in place, and the empty message is reserved for a served
 * empty list.
 */

const DEMO_ENVIRONMENT = { version: 1, demo_mode: true, execution: 'preview_only', notice: 'Demo environment: preview and replay only.' };
const EMPTY_CATALOG = { categories: [], task_types: [] };

type DemoModule = typeof import('../src/features/demo/index');

function reply(payload: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => payload } as unknown as Response;
}

async function load(): Promise<DemoModule> {
  vi.resetModules();
  installHarness(vi.stubGlobal, { pathname: '/compute/demo' });
  return await import('../src/features/demo/index');
}

function routeFetch(replays: () => Response): void {
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = String(input);
    if (url === '/compute/api/environment') return reply(DEMO_ENVIRONMENT);
    if (url === '/compute/api/types') return reply(EMPTY_CATALOG);
    if (url === '/compute/api/demo/replays') return replays();
    throw new Error(`unexpected request ${url}`);
  }));
}

async function landing(demo: DemoModule): Promise<HarnessNode> {
  const root = document.createElement('div') as unknown as HarnessNode;
  await demo.mountDemoLanding(root as unknown as HTMLElement);
  return root;
}

afterEach(() => vi.unstubAllGlobals());

describe('the demo playground replay catalog', () => {
  it('states a read failure and retries instead of claiming nothing is installed', async () => {
    const demo = await load();
    const replays = vi.fn()
      .mockReturnValueOnce(reply({ error: 'unavailable' }, 503))
      .mockReturnValueOnce(reply({ scenarios: [] }));
    routeFetch(replays);
    const root = await landing(demo);

    expect(root.textContent).not.toContain('No replay scenarios are installed');
    expect(root.textContent).toContain('Could not load recorded results: HTTP 503');
    const retry = root.querySelector('.demo-section button.secondary-button')!;
    expect(retry.textContent).toBe('Retry');

    retry.dispatch('click', {});
    await vi.waitFor(() => expect(root.textContent).toContain('No replay scenarios are installed'));
    expect(replays).toHaveBeenCalledTimes(2);
  });

  it('reports an empty served catalog as none installed, without a failure', async () => {
    const demo = await load();
    routeFetch(() => reply({ scenarios: [] }));
    const root = await landing(demo);
    expect(root.textContent).toContain('No replay scenarios are installed');
    expect(root.textContent).not.toContain('Could not load recorded results');
  });

  it('gives the replay page a failure state with a retry', async () => {
    const demo = await load();
    routeFetch(() => reply({ error: 'unavailable' }, 500));
    const root = document.createElement('div') as unknown as HarnessNode;
    const view = await demo.mountDemoReplay(root as unknown as HTMLElement, 'missing');
    expect(view).not.toBeNull();
    expect(root.textContent).toContain('Could not load recorded results: HTTP 500');
    expect(root.querySelector('button.secondary-button')!.textContent).toBe('Retry');
  });
});
