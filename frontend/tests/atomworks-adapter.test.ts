import { afterEach, describe, expect, it, vi } from 'vitest';

import { builderAdapters } from '../src/features/create-task/input-workspace/builders';
import { HarnessNode, installHarness } from './dom-harness';

type MessageListener = (event: unknown) => void;

function installMessageWindow(): { dispatch: (event: unknown) => void } {
  const listeners: MessageListener[] = [];
  vi.stubGlobal('window', {
    location: { origin: 'https://revocompute.invalid' },
    addEventListener: (type: string, listener: MessageListener) => {
      if (type === 'message') listeners.push(listener);
    },
    removeEventListener: (type: string, listener: MessageListener) => {
      if (type !== 'message') return;
      const index = listeners.indexOf(listener);
      if (index >= 0) listeners.splice(index, 1);
    },
  });
  return { dispatch: event => listeners.forEach(listener => listener(event)) };
}

function sessionResponse(id: string): Response {
  return new Response(JSON.stringify({ session_id: id, editor_path: `/?session=${id}&embed=1` }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  });
}

function exportResponse(cif: string): Response {
  return new Response(JSON.stringify({ cif, name: 'condition', revision: 1, issues: [] }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  });
}

async function mountAdapter() {
  const container = new HarnessNode('DIV');
  const adapter = await builderAdapters.atomworks!.mount(
    container as unknown as HTMLElement, { target: 'rfd4' },
  );
  const input = container.querySelector('input')! as unknown as { files: File[] };
  const open = container.querySelector('button')!;
  return {
    container, adapter, input, open,
    choose(name: string, content: string): void {
      input.files = [new File([content], name)];
      open.dispatch('click', new Event('click'));
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe('AtomWorks adapter session lifecycle', () => {
  it('invalidates a bound output when a new document replacement is initiated', async () => {
    installHarness(vi.stubGlobal);
    installMessageWindow();
    const deleted: string[] = [];
    let nextSession = 'sid-a';
    let exported = 'A-export';
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method || 'GET';
      if (url === '/api/sessions' && method === 'POST') return sessionResponse(nextSession);
      if (method === 'DELETE') { deleted.push(url); return new Response(null, { status: 204 }); }
      if (url.endsWith('/export')) return exportResponse(exported);
      throw new Error(`unexpected request ${method} ${url}`);
    }));
    const { container, adapter, choose } = await mountAdapter();
    const changes = vi.fn();
    adapter.subscribe(changes);

    choose('first.cif', 'first');
    await vi.waitFor(() => expect(container.querySelector('iframe')).not.toBeNull());
    await adapter.restore({ format: 'annotated-cif', cif: 'restored' });
    changes.mockClear();

    // A replacement is an edit at initiation, before the new session is even
    // created: the previously applied bytes must stop being submittable.
    nextSession = 'sid-b';
    exported = 'B-export';
    choose('second.cif', 'second');
    expect(changes).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(deleted).toContain('/api/sessions/sid-a'));
    await vi.waitFor(() => expect(container.querySelector('iframe')).not.toBeNull());

    const materialized = await adapter.materialize();
    expect(materialized.snapshot).toEqual({ format: 'annotated-cif', cif: 'B-export' });
  });

  it('does not install or leak a session created after teardown', async () => {
    installHarness(vi.stubGlobal);
    installMessageWindow();
    const deleted: string[] = [];
    let resolveCreate!: (response: Response) => void;
    const create = new Promise<Response>(resolve => { resolveCreate = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method || 'GET';
      if (url === '/api/sessions' && method === 'POST') return create;
      if (method === 'DELETE') { deleted.push(url); return new Response(null, { status: 204 }); }
      throw new Error(`unexpected request ${method} ${url}`);
    }));
    const { container, adapter, choose } = await mountAdapter();

    choose('late.cif', 'late');
    await Promise.resolve();
    adapter.destroy();
    resolveCreate(sessionResponse('sid-late'));

    await vi.waitFor(() => expect(deleted).toContain('/api/sessions/sid-late'));
    expect(container.querySelector('iframe')).toBeNull();
    await expect(adapter.materialize()).rejects.toThrow(/Open an AtomWorks Studio session/);
  });

  it('accepts change messages only from this editor frame on this origin', async () => {
    installHarness(vi.stubGlobal);
    const messaging = installMessageWindow();
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method || 'GET';
      if (url === '/api/sessions' && method === 'POST') return sessionResponse('sid-a');
      if (method === 'DELETE') return new Response(null, { status: 204 });
      throw new Error(`unexpected request ${method} ${url}`);
    }));
    const { container, adapter, choose } = await mountAdapter();
    const changes = vi.fn();
    adapter.subscribe(changes);

    choose('first.cif', 'first');
    await vi.waitFor(() => expect(container.querySelector('iframe')).not.toBeNull());
    changes.mockClear();
    const frame = container.querySelector('iframe')! as unknown as { contentWindow: unknown };
    frame.contentWindow = {};
    const payload = { source: 'atomworks-annotation-studio', type: 'changed', session_id: 'sid-a' };

    messaging.dispatch({ source: frame.contentWindow, origin: 'https://evil.invalid', data: payload });
    expect(changes).not.toHaveBeenCalled();
    messaging.dispatch({ source: frame.contentWindow, origin: 'https://revocompute.invalid', data: payload });
    expect(changes).toHaveBeenCalledOnce();
  });
});
