import { afterEach, describe, expect, it, vi } from 'vitest';

import { PluginHost } from '../src/features/create-task/input-workspace/PluginHost';
import type { WorkspaceContext, WorkspacePlugin } from '../src/features/create-task/input-workspace/plugin-contract';
import type { WorkspaceCapability, WorkspaceDescriptor } from '../src/features/create-task/types';

class FakeElement {
  rel = ''; href = ''; type = ''; className = ''; textContent = ''; dataset: Record<string, string> = {};
  removed = false;
  append(): void {}
  remove(): void { this.removed = true; }
  replaceChildren(): void {}
}

afterEach(() => vi.unstubAllGlobals());

describe('Create Task workspace PluginHost', () => {
  it('mounts a descriptor module by its task-local capability id and removes styles on destroy', async () => {
    const links: FakeElement[] = [];
    vi.stubGlobal('document', {
      createElement: () => new FakeElement(),
      head: { append: (link: FakeElement) => links.push(link) },
    });
    const destroy = vi.fn(); const plugin: WorkspacePlugin = { id: 'regions', mount: () => ({ readValue: () => ({ mode: 'binder' }), destroy }) };
    const host = new PluginHost([], { fetch }, vi.fn(async () => ({ default: plugin })));
    const descriptor: WorkspaceDescriptor = {
      id: 'regions', owner: 'runner', global_id: 'runner:regions', descriptor_url: '/compute/api/workspace/plugins/runner/regions',
      module: { url: '/compute/api/workspace/assets/runner/regions/index.js', type: 'module' },
      stylesheets: [{ url: '/compute/api/workspace/assets/runner/regions/style.css', media_type: 'text/css' }],
    };
    await host.load([descriptor]);
    const capability: WorkspaceCapability = { plugin: 'regions', id: 'design', title: 'Regions', options: {}, stepId: 'intent' };
    host.mount([capability], {} as WorkspaceContext, () => new FakeElement() as unknown as HTMLElement);
    expect(host.collect()).toEqual({ design: { mode: 'binder' } });
    host.destroy();
    expect(destroy).toHaveBeenCalledOnce(); expect(links[0]?.removed).toBe(true);

    const remounted = new PluginHost([], { fetch }, vi.fn(async () => ({ default: plugin })));
    await remounted.load([descriptor]);
    remounted.mount([capability], {} as WorkspaceContext, () => new FakeElement() as unknown as HTMLElement);
    expect(remounted.collect()).toEqual({ design: { mode: 'binder' } });
    expect(links).toHaveLength(2);
    remounted.destroy();
  });

  it('isolates validation failures from healthy plugins', () => {
    vi.stubGlobal('document', { createElement: () => new FakeElement(), head: { append: vi.fn() } });
    const good: WorkspacePlugin = { id: 'good', mount: () => ({ validate: () => 'Fix good input' }) };
    const bad: WorkspacePlugin = { id: 'bad', mount: () => ({ validate: () => { throw new Error('broken validator'); } }) };
    const host = new PluginHost([good, bad], { fetch });
    const capability = (plugin: string): WorkspaceCapability => ({ plugin, id: plugin, title: plugin, options: {}, stepId: 'one' });
    host.mount([capability('good'), capability('bad')], {} as WorkspaceContext, () => new FakeElement() as unknown as HTMLElement);
    expect(host.validate()).toEqual(['Fix good input', 'bad: broken validator']);
  });

  it('isolates a failed Runner module while retaining builtin capabilities', async () => {
    vi.stubGlobal('document', { createElement: () => new FakeElement(), head: { append: vi.fn() } });
    const builtin: WorkspacePlugin = { id: 'files', mount: () => ({ validate: () => null }) };
    const host = new PluginHost([builtin], { fetch }, vi.fn(async () => { throw new Error('module unavailable'); }));
    await host.load([{
      id: 'regions', owner: 'runner', global_id: 'runner:regions',
      descriptor_url: '/compute/api/workspace/plugins/runner/regions',
      module: { url: '/compute/api/workspace/assets/runner/regions/index.js', type: 'module' }, stylesheets: [],
    }]);
    host.mount([
      { plugin: 'files', id: 'files', title: 'Files', options: {}, stepId: 'one' },
      { plugin: 'regions', id: 'regions', title: 'Regions', options: {}, stepId: 'one' },
    ], {} as WorkspaceContext, () => new FakeElement() as unknown as HTMLElement);
    expect(host.validate()).toEqual([
      'runner:regions: module unavailable',
      'regions: unsupported component',
    ]);
  });

  it('discards a deferred Runner module and its styles after teardown', async () => {
    const links: FakeElement[] = [];
    vi.stubGlobal('document', {
      createElement: () => new FakeElement(),
      head: { append: (link: FakeElement) => links.push(link) },
    });
    let resolveModule!: (value: unknown) => void;
    const deferred = new Promise<unknown>(resolve => { resolveModule = resolve; });
    const plugin: WorkspacePlugin = { id: 'regions', mount: () => ({ readValue: () => 'stale' }) };
    const host = new PluginHost([], { fetch }, () => deferred);
    const loading = host.load([{
      id: 'regions', owner: 'runner', global_id: 'runner:regions',
      descriptor_url: '/compute/api/workspace/plugins/runner/regions',
      module: { url: '/compute/api/workspace/assets/runner/regions/index.js', type: 'module' },
      stylesheets: [{ url: '/compute/api/workspace/assets/runner/regions/style.css', media_type: 'text/css' }],
    }]);
    host.destroy(); resolveModule({ default: plugin }); await loading;
    expect(links).toHaveLength(0);
    host.mount([{ plugin: 'regions', id: 'regions', title: 'Regions', options: {}, stepId: 'one' }], {} as WorkspaceContext, () => new FakeElement() as unknown as HTMLElement);
    expect(host.collect()).toEqual({});
    expect(host.validate()).toContain('regions: unsupported component');
  });

  it('contains asynchronous refresh failures as validation errors', async () => {
    vi.stubGlobal('document', { createElement: () => new FakeElement(), head: { append: vi.fn() } });
    const plugin: WorkspacePlugin = { id: 'async', mount: () => ({ refresh: async () => { throw new Error('refresh failed'); } }) };
    const host = new PluginHost([plugin], { fetch });
    host.mount([{ plugin: 'async', id: 'async', title: 'Async', options: {}, stepId: 'one' }], {} as WorkspaceContext, () => new FakeElement() as unknown as HTMLElement);
    host.refresh(); await Promise.resolve(); await Promise.resolve();
    expect(host.validate()).toContain('async: refresh failed');
  });
});
