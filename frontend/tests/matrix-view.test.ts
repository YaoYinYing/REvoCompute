import { afterEach, describe, expect, it, vi } from 'vitest';

import { createMatrixViewRenderer, loadMatrixSeries, matrixRamp, matrixRange } from '../src/features/results/matrix-view';

/** Serve one synthetic table page per request, honouring `offset`/`limit` like the server route. */
function servePages(rows: string[][], columns: string[], pageLimit: number) {
  const calls: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(url);
    const parsed = new URL(url, 'https://example.invalid');
    const offset = Number(parsed.searchParams.get('offset'));
    const limit = Math.min(Number(parsed.searchParams.get('limit')), pageLimit);
    const page = rows.slice(offset, offset + limit);
    return new Response(JSON.stringify({
      columns, rows: page, offset, limit, has_more: offset + page.length < rows.length,
    }), { status: 200 });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe('loadMatrixSeries', () => {
  it('assembles paged rows into a labelled square matrix on the bounded table URL', async () => {
    const columns = ['position', '1', '2', '3'];
    const rows = [['1', '0', '1', '2'], ['2', '1', '0', '3'], ['3', '2', '3', '0']];
    const calls = servePages(rows, columns, 2);
    const series = await loadMatrixSeries('/tables/couplings.csv', { row_labels_column: 'position' });

    expect(series).toEqual({
      values: [[0, 1, 2], [1, 0, 3], [2, 3, 0]],
      xLabels: ['1', '2', '3'],
      yLabels: ['1', '2', '3'],
    });
    expect(calls).toHaveLength(2);
    expect(calls[0]).toContain('matrix=1');
    expect(calls[0]).toContain('limit=500');
    expect(calls[1]).toContain('offset=2');
    expect(calls[0]).toContain('/tables/couplings.csv?');
  });

  it('parses negative, zero, blank, and large values without inventing meaning', async () => {
    const columns = ['position', '1', '2', '3'];
    const rows = [['1', '-7.5', '0', '912.25'], ['2', '0', '', '1e3'], ['3', '3', '4', '5']];
    servePages(rows, columns, 500);
    const series = await loadMatrixSeries('/tables/m.csv', { row_labels_column: 'position' });
    expect(series.values).toEqual([[-7.5, 0, 912.25], [0, null, 1000], [3, 4, 5]]);
  });

  it('reads a matrix whose label column is unnamed by falling back to the header labels', async () => {
    servePages([['1', '2'], ['3', '4']], ['1', '2'], 500);
    const series = await loadMatrixSeries('/tables/m.csv', {});
    expect(series).toEqual({ values: [[1, 2], [3, 4]], xLabels: ['1', '2'], yLabels: [] });
  });

  it('rejects a missing table URL, a missing declared label column, and non-numeric cells', async () => {
    await expect(loadMatrixSeries(undefined, { row_labels_column: 'position' })).rejects.toThrow('no bounded table URL');
    servePages([['1', '2']], ['1', '2'], 500);
    await expect(loadMatrixSeries('/tables/m.csv', { row_labels_column: 'position' })).rejects.toThrow('missing its declared row label column');
    servePages([['alpha', '2']], ['1', '2'], 500);
    await expect(loadMatrixSeries('/tables/m.csv', {})).rejects.toThrow('not a number');
  });

  it('accepts a full-width matrix page of 512 values plus its label column', async () => {
    const columns = ['position', ...Array.from({ length: 512 }, (_, index) => String(index + 1))];
    const row = ['1', ...Array.from({ length: 512 }, (_, index) => String(index))];
    servePages([row], columns, 500);
    const series = await loadMatrixSeries('/tables/m.csv', { row_labels_column: 'position' });
    expect(series.xLabels).toHaveLength(512);
    expect(series.values[0]).toHaveLength(512);
    expect(series.yLabels).toEqual(['1']);

    const tooWide = ['position', ...Array.from({ length: 513 }, (_, index) => String(index + 1))];
    servePages([['1', ...Array.from({ length: 513 }, () => '0')]], tooWide, 500);
    await expect(loadMatrixSeries('/tables/m.csv', { row_labels_column: 'position' })).rejects.toThrow('malformed');
  });

  it('refuses a matrix that exceeds the browser element budget', async () => {
    servePages([['1', '2', '3'], ['4', '5', '6']], ['1', '2', '3'], 500);
    await expect(loadMatrixSeries('/tables/m.csv', {}, { maxElements: 3 })).rejects.toThrow('exceeds the browser element limit');
  });

  it('surfaces a failed page request instead of assembling a partial matrix', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"error":"nope"}', { status: 404 })));
    await expect(loadMatrixSeries('/tables/m.csv', {})).rejects.toThrow('could not be loaded');
  });

  it('propagates abort and rejects a malformed page shape', async () => {
    const controller = new AbortController(); controller.abort();
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return new Response();
    }));
    await expect(loadMatrixSeries('/tables/m.csv', {}, { signal: controller.signal })).rejects.toHaveProperty('name', 'AbortError');
    servePages([['1', '2', '3']], ['position', '1'], 500);
    await expect(loadMatrixSeries('/tables/m.csv', { row_labels_column: 'position' })).rejects.toThrow('malformed');
  });
});

describe('matrixRange', () => {
  it('makes a diverging range symmetric about a zero centre so negatives render', () => {
    expect(matrixRange([[-7.5, 0, 2.5], [1, 0, 3]], { scale: 'diverging', center: 0 }))
      .toEqual({ minimum: -7.5, maximum: 7.5 });
    expect(matrixRange([[0, 4], [9, 0]], { scale: 'diverging', center: 0 })).toEqual({ minimum: -9, maximum: 9 });
  });

  it('honours a non-zero diverging centre and declared scale bounds', () => {
    expect(matrixRange([[-1, 5]], { scale: 'diverging', center: 2 })).toEqual({ minimum: -1, maximum: 5 });
    expect(matrixRange([[-3, 4]], { scale: 'diverging', center: 0, scale_min: -10, scale_max: 10 }))
      .toEqual({ minimum: -10, maximum: 10 });
  });

  it('keeps a monotonic observed extent for a sequential scale and never divides by zero', () => {
    expect(matrixRange([[-2, 4]], { scale: 'sequential' })).toEqual({ minimum: -2, maximum: 4 });
    expect(matrixRange([[3, 3]], { scale: 'sequential' })).toEqual({ minimum: 3, maximum: 4 });
    expect(matrixRange([[null, null]], { scale: 'sequential' })).toBeNull();
  });

  it('selects a diverging ramp that is neutral at its midpoint and a sequential ramp that is not', () => {
    const diverging = matrixRamp('diverging', 'light');
    expect(diverging).toHaveLength(5);
    expect(diverging[Math.floor(diverging.length / 2)]).toBe('#f0efec');
    expect(matrixRamp('sequential', 'light')).toEqual(['#eef7fb', '#7db9dc', '#155b8a']);
    expect(matrixRamp('diverging', 'dark')).not.toEqual(diverging);
  });
});

class TestElement {
  className = '';
  tabIndex = 0;
  textContent = '';
  children: unknown[] = [];
  parentElement: TestElement | null = null;
  readonly style = {};
  setAttribute(): void {}
  append(...nodes: unknown[]): void { this.children.push(...nodes); }
  replaceChildren(...nodes: unknown[]): void { this.children = nodes; }
  prepend(...nodes: unknown[]): void { this.children.unshift(...nodes); }
  addEventListener(): void {}
  removeEventListener(): void {}
  querySelectorAll(): unknown[] { return []; }
  getContext(): null { return null; }
}

describe('matrix view renderer', () => {
  it('draws the declared view through PairMatrix, not a table, and reports the failure reason on fallback', async () => {
    const table = {
      path: 'couplings/apc_scores.csv', size: 10, sha256: 'a'.repeat(64), url: '/artifacts/apc',
      table_url: '/tables/apc', media_type: 'text/csv', preview: 'table', capability: 'table', role: 'primary',
    };
    const view = {
      id: 'apc_couplings', plugin: 'matrix', role: 'primary', title: 'APC coupling strengths',
      description: 'Frobenius norms.', sources: { matrices: ['couplings/apc_scores.csv'] },
      mapping: { format: 'csv', row_labels_column: 'position', unit: 'coupling score', scale: 'diverging', center: 0 },
    };
    servePages([['1', '-2', '3'], ['2', '3', '-2']], ['position', '1', '2'], 500);
    const renderer = createMatrixViewRenderer();
    vi.stubGlobal('window', { devicePixelRatio: 1 });
    vi.stubGlobal('document', {
      createElement: () => new TestElement(),
      documentElement: { dataset: {} },
    });
    const host = new TestElement();
    const destroy = await renderer.render(view as never, table as never, host as unknown as HTMLElement, {
      signal: new AbortController().signal, taskId: 'a'.repeat(32),
    });
    const split = host.children[0] as TestElement;
    expect(split.className).toBe('pair-matrix-view');
    expect((split.children[0] as TestElement).className).toBe('pair-matrix-figure');
    expect((destroy as { destroy(): void }).destroy).toBeTypeOf('function');

    servePages([], ['position', '1'], 500);
    await expect(renderer.render(view as never, table as never, host as unknown as HTMLElement, {
      signal: new AbortController().signal, taskId: 'a'.repeat(32),
    })).rejects.toThrow('empty');
  });

  it('refuses a view whose source artifact has no table capability', async () => {
    const renderer = createMatrixViewRenderer();
    const view = { id: 'm', plugin: 'matrix', role: 'evidence', title: 'M', sources: { matrices: ['m.csv'] }, mapping: {} };
    const artifact = { path: 'm.csv', size: 1, sha256: 'a'.repeat(64), url: '/artifacts/m', media_type: 'text/csv',
      preview: 'text', capability: 'text', role: 'evidence' };
    await expect(renderer.render(view as never, artifact as never, new TestElement() as unknown as HTMLElement, {
      signal: new AbortController().signal, taskId: 'a'.repeat(32),
    })).rejects.toThrow('no bounded table URL');
  });
});
