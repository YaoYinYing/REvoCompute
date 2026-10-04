import { describe, expect, it, vi } from 'vitest';

import { StoryboardHost } from '../src/features/results/storyboard-host';

vi.mock('storyboard-probe', () => ({
  default: {
    mount(_host: HTMLElement, context: unknown) {
      (globalThis as { __storyboardContext?: unknown }).__storyboardContext = context;
      return { destroy: vi.fn() };
    },
  },
}));

describe('StoryboardHost preview ownership', () => {
  it('does not clear a preview it never mounted', () => {
    const child = {} as Node;
    const host = { replaceChildren: vi.fn(), firstChild: child } as unknown as HTMLElement;
    const storyboard = new StoryboardHost(host, { openFile: vi.fn(), downloadFile: vi.fn() });
    storyboard.destroy();
    expect(host.replaceChildren).not.toHaveBeenCalled();
  });
});

describe('StoryboardHost mount context', () => {
  it('exposes the manifest views and the openView service beside the frozen file map', async () => {
    const host = { replaceChildren: vi.fn(), firstChild: null } as unknown as HTMLElement;
    const openView = vi.fn(async () => {});
    const storyboard = new StoryboardHost(host, { openFile: vi.fn(), downloadFile: vi.fn(), openView });
    const declaration = { identifier: 'probe', entrypoint: 'index.js', entrypoint_url: 'storyboard-probe', requires: [], optional: [] };
    const views = [{ id: 'apc_couplings', plugin: 'matrix', role: 'primary', title: 'APC', sources: { matrices: ['m.csv'] } }];
    const manifest = { task_type: 'gremlin_lh_fit', views, result: { files: {} } };

    const mounted = await storyboard.mount(declaration as never, manifest as never);
    expect(mounted).toBe(true);
    const context = (globalThis as { __storyboardContext?: {
      views: unknown; metadata: unknown; services: { openView(id: string): Promise<void> };
    } }).__storyboardContext!;
    expect(context.views).toEqual(views);
    expect(Object.isFrozen(context.views)).toBe(true);
    expect(context.metadata).toEqual({ taskType: 'gremlin_lh_fit' });
    await context.services.openView('apc_couplings');
    expect(openView).toHaveBeenCalledWith('apc_couplings');
  });

  it('declares no views when the manifest omits them', async () => {
    const host = { replaceChildren: vi.fn(), firstChild: null } as unknown as HTMLElement;
    const storyboard = new StoryboardHost(host, { openFile: vi.fn(), downloadFile: vi.fn() });
    const declaration = { identifier: 'probe', entrypoint: 'index.js', entrypoint_url: 'storyboard-probe', requires: [], optional: [] };
    await storyboard.mount(declaration as never, { task_type: 'x', result: { files: {} } } as never);
    const context = (globalThis as { __storyboardContext?: { views: unknown } }).__storyboardContext!;
    expect(context.views).toEqual([]);
  });
});
