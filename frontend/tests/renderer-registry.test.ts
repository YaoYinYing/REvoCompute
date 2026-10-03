import { afterEach, describe, expect, it, vi } from 'vitest';

import type { LogicalResultFile, ResultView } from '../src/api/result-types';
import { createBasicRenderers, ViewRendererRegistry } from '../src/features/results/renderer-registry';

class TestNode {
  className = '';
  scope = '';
  textContent = '';
  append(..._children: unknown[]): void {}
  replaceChildren(..._children: unknown[]): void {}
}

const logicalTable = (tableUrl?: string): LogicalResultFile => ({
  id: 'scores', name: 'scores.csv', media_type: 'text/csv', size: 8, role: 'evidence', cardinality: 'one',
  viewer: 'table', preview: 'table', capability: 'table', url: '/logical/scores', table_url: tableUrl,
});

afterEach(() => vi.unstubAllGlobals());

describe('view renderer registry', () => {
  it('dispatches only on the declared plugin and rejects a duplicate registration', () => {
    const registry = new ViewRendererRegistry()
      .register({ id: 'matrix', render: async () => {} });
    const view = (id: string, plugin: string): ResultView =>
      ({ id, plugin, role: 'evidence', title: id, sources: { matrices: ['m.csv'] } }) as ResultView;

    expect(registry.resolve(view('a', 'matrix'))?.id).toBe('matrix');
    expect(registry.resolve(view('b', 'entity-table'))).toBeNull();
    expect(() => registry.register({ id: 'matrix', render: async () => {} })).toThrow('Duplicate view renderer: matrix');
  });
});

describe('table renderer', () => {
  it('uses the authoritative logical-file table URL and never infers one from its basename', async () => {
    vi.stubGlobal('document', { createElement: () => new TestNode() });
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ columns: ['score'], rows: [[1]], has_more: false })));
    vi.stubGlobal('fetch', fetchMock);
    const renderer = createBasicRenderers().find((candidate) => candidate.id === 'table')!;

    await renderer.render(logicalTable('/authorized/table/scores'), new TestNode() as unknown as HTMLElement, {
      signal: new AbortController().signal, taskId: 'a'.repeat(32),
    });
    expect(fetchMock).toHaveBeenCalledWith('/authorized/table/scores', expect.objectContaining({ credentials: 'same-origin' }));

    await expect(renderer.render(logicalTable(), new TestNode() as unknown as HTMLElement, {
      signal: new AbortController().signal, taskId: 'a'.repeat(32),
    })).rejects.toThrow('no authorized preview URL');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
