import { afterEach, describe, expect, it, vi } from 'vitest';

import { createEntityTableViewRenderer, entityColumns } from '../src/features/results/entity-table-view';
import { createMetricSeriesViewRenderer, seriesRange, seriesValues } from '../src/features/results/metric-series-view';
import { loadTable, tableUrlOf } from '../src/features/results/table-page';
import { installHarness, type HarnessNode } from './dom-harness';

/** Serve one synthetic table page per request, honouring `offset`/`limit` like the server route. */
function servePages(rows: string[][], columns: string[], pageLimit: number) {
  const calls: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(url);
    const parsed = new URL(url, 'https://example.invalid');
    const offset = Number(parsed.searchParams.get('offset'));
    const limit = Math.min(Number(parsed.searchParams.get('limit')), pageLimit);
    const page = rows.slice(offset, offset + limit);
    return new Response(JSON.stringify({ columns, rows: page, offset, limit, has_more: offset + page.length < rows.length }), { status: 200 });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe('loadTable', () => {
  it('walks the bounded page window and keeps every declared column', async () => {
    const calls = servePages([['A1V', '1.2'], ['A1G', '-0.4'], ['A1P', '0.1']], ['mutation', 'score'], 2);
    const { page, truncated } = await loadTable('/tables/scores.csv');
    expect(page.columns).toEqual(['mutation', 'score']);
    expect(page.rows).toEqual([['A1V', '1.2'], ['A1G', '-0.4'], ['A1P', '0.1']]);
    expect(truncated).toBe(false);
    expect(calls).toHaveLength(2);
    expect(calls[0]).toContain('limit=500');
    expect(calls[1]).toContain('offset=2');
  });

  it('stops at the row budget and reports the table as truncated', async () => {
    servePages([['1'], ['2'], ['3'], ['4']], ['position'], 2);
    const { page, truncated } = await loadTable('/tables/profile.csv', { maxRows: 2 });
    expect(page.rows).toEqual([['1'], ['2']]);
    expect(truncated).toBe(true);
  });

  it('rejects a missing URL, a failed page, and a page whose shape changes mid-walk', async () => {
    await expect(loadTable(undefined)).rejects.toThrow('no bounded table URL');
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"error":"nope"}', { status: 404 })));
    await expect(loadTable('/tables/scores.csv')).rejects.toThrow('could not be loaded');
    let page = 0;
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(page++ === 0
      ? { columns: ['a', 'b'], rows: [['1', '2']], has_more: true }
      : { columns: ['a'], rows: [['3']], has_more: false }), { status: 200 })));
    await expect(loadTable('/tables/scores.csv')).rejects.toThrow('malformed');
  });

  it('resolves a bounded table URL from the source artifact or its published path', () => {
    expect(tableUrlOf({ path: 'scores.csv', table_url: '/tables/scores.csv' } as never, 'a'.repeat(32)))
      .toBe('/tables/scores.csv');
    expect(tableUrlOf({ path: 'nested dir/scores.csv', url: '/artifacts/x' } as never, 'a'.repeat(32)))
      .toContain('/tables/nested%20dir/scores.csv');
    // A logical file's published path is identity, not a route: without the
    // Server's own table URL the view asks for none.
    expect(tableUrlOf({ id: 'scores', name: 'scores.csv', path: 'nested/scores.csv', url: '/files/scores?index=0' } as never,
      'a'.repeat(32))).toBeUndefined();
    expect(tableUrlOf(undefined, 'a'.repeat(32))).toBeUndefined();
  });
});

describe('entity table columns', () => {
  it('presents the declared label, key, and evidence columns without duplicating a name', () => {
    expect(entityColumns({ label_column: 'mutation', key_columns: ['mutation'], evidence_columns: ['mean_score'] },
      ['mutation', 'score_1', 'mean_score'])).toEqual(['mutation', 'mean_score']);
    expect(entityColumns({ key_columns: ['chain', 'residue_number'], evidence_columns: ['embedding_norm'] },
      ['row', 'chain', 'residue_number', 'amino_acid', 'embedding_norm'])).toEqual(['chain', 'residue_number', 'embedding_norm']);
  });

  it('refuses a mapping whose columns the table does not publish', () => {
    expect(() => entityColumns({ label_column: 'mutation' }, ['position', 'score'])).toThrow('declares no column');
  });
});

describe('entity-table declared structure', () => {
  const structure = { path: 'enzyme_structure.pdb', media_type: 'chemical/x-pdb', size: 10, sha256: 'b'.repeat(64), url: '/artifacts/enzyme_structure.pdb' };
  const activeSites = {
    id: 'active_sites', plugin: 'entity-table', role: 'primary', title: 'Active-site mapping',
    sources: { table: ['active_sites.csv'], structure: ['enzyme_structure.pdb'] },
    mapping: { entity: 'residue', key_columns: ['chain', 'residue_index'], label_column: 'site_name',
      chain_column: 'chain', residue_column: 'residue_index', numbering: 'label_seq_id', evidence_columns: ['site_class'] },
  };
  const tableSource = { table: [{ path: 'active_sites.csv', size: 10, sha256: 'a'.repeat(64), url: '/artifacts/a', table_url: '/tables/a' }] };
  const rows = [['siteA', 'A', '42', 'catalytic'], ['siteB', 'B', '7', 'binding']];
  const columns = ['site_name', 'chain', 'residue_index', 'site_class'];

  it('mounts the declared structure beside the table', async () => {
    installHarness(vi.stubGlobal);
    servePages(rows, columns, 500);
    const opened: string[] = [];
    const host = document.createElement('section') as unknown as HarnessNode;
    const instance = await createEntityTableViewRenderer().render(activeSites as never,
      { ...tableSource, structure: [structure] } as never, host as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32),
        openStructure: async (artifact, stage) => { opened.push(artifact.url); stage.append(document.createElement('div')); } });
    expect(opened).toEqual([structure.url]);
    expect(host.querySelector('.entity-table-stage')).not.toBeNull();
    expect(host.querySelector('.entity-table-stage')!.children).toHaveLength(1);
    expect(host.querySelectorAll('tr')).toHaveLength(3);
    (instance as { destroy(): void }).destroy();
  });

  it('selects the declared residue of a row and replaces it with the next row', async () => {
    installHarness(vi.stubGlobal);
    servePages(rows, columns, 500);
    const selections: unknown[] = [];
    const host = document.createElement('section') as unknown as HarnessNode;
    const instance = await createEntityTableViewRenderer().render(activeSites as never,
      { ...tableSource, structure: [structure] } as never, host as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32),
        openStructure: async () => undefined, selectStructure: (selection) => selections.push(selection) });
    const lines = host.querySelectorAll('tr').slice(1);
    lines[0]!.dispatch('click', {});
    lines[1]!.dispatch('click', {});
    expect(selections).toEqual([
      { chain: 'A', residue: 42, numbering: 'label_seq_id' },
      { chain: 'B', residue: 7, numbering: 'label_seq_id' },
    ]);
    (instance as { destroy(): void }).destroy();
  });

  it('closes the stage it mounted when the view is superseded', async () => {
    installHarness(vi.stubGlobal);
    servePages(rows, columns, 500);
    const closed: unknown[] = [];
    const host = document.createElement('section') as unknown as HarnessNode;
    const instance = await createEntityTableViewRenderer().render(activeSites as never,
      { ...tableSource, structure: [structure] } as never, host as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32),
        openStructure: async () => undefined, closeStructure: (stage) => { closed.push(stage); } });
    const stage = host.querySelector('.entity-table-stage');
    (instance as { destroy(): void }).destroy();
    // The view closes the exact stage node it mounted, never a stage chosen by name.
    expect(closed).toEqual([stage]);
  });

  it('renders only the table when the view declares no structure', async () => {
    installHarness(vi.stubGlobal);
    servePages(rows, columns, 500);
    const openStructure = vi.fn(async () => undefined);
    const selectStructure = vi.fn();
    const host = document.createElement('section') as unknown as HarnessNode;
    const view = { ...activeSites, sources: { table: ['active_sites.csv'] } };
    const instance = await createEntityTableViewRenderer().render(view as never, tableSource as never,
      host as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32), openStructure, selectStructure });
    host.querySelectorAll('tr')[1]!.dispatch('click', {});
    expect(host.querySelector('table.entity-result-table')).not.toBeNull();
    expect(host.querySelector('.entity-table-stage')).toBeNull();
    expect(openStructure).not.toHaveBeenCalled();
    expect(selectStructure).not.toHaveBeenCalled();
    (instance as { destroy(): void }).destroy();
  });

  it('states a failed structure mount, leaves no stage, and clears everything on destroy', async () => {
    installHarness(vi.stubGlobal);
    servePages(rows, columns, 500);
    const host = document.createElement('section') as unknown as HarnessNode;
    const instance = await createEntityTableViewRenderer().render(activeSites as never,
      { ...tableSource, structure: [structure] } as never, host as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32),
        openStructure: async () => { throw new Error('The structure could not be parsed.'); } });
    expect(host.querySelector('.entity-table-stage')).toBeNull();
    expect(host.textContent).toContain('The structure could not be parsed.');
    expect(host.querySelector('table.entity-result-table')).not.toBeNull();
    (instance as { destroy(): void }).destroy();
    expect(host.querySelector('table')).toBeNull();
    expect(host.textContent).not.toContain('The structure could not be parsed.');
  });
});

describe('metric series values and range', () => {
  it('keeps a blank or NA cell as a gap and preserves negative values', () => {
    expect(seriesValues(['-2.5', '', 'NA', '0', '1e3'])).toEqual([-2.5, null, null, 0, 1000]);
  });

  it('honours declared bounds over the observed extent and never produces an empty range', () => {
    expect(seriesRange([-4, 2, null], {})).toEqual({ minimum: -4, maximum: 2 });
    expect(seriesRange([-4, 2], { y_min: 0, y_max: 100 })).toEqual({ minimum: 0, maximum: 100 });
    expect(seriesRange([null], {})).toEqual({ minimum: 0, maximum: 1 });
  });
});

describe('entity-table and metric-series renderers', () => {
  it('renders the declared columns and reports truncation in the DOM', async () => {
    installHarness(vi.stubGlobal);
    servePages([['A1V', '1'], ['A1G', '2'], ['A1P', '3']], ['mutation', 'mean_score'], 2);
    const host = document.createElement('section') as unknown as HarnessNode;
    const view = { id: 'mutation_scores', plugin: 'entity-table', role: 'primary', title: 'Scores',
      sources: { table: ['scores.csv'] }, mapping: { entity: 'mutation', key_columns: ['mutation'], evidence_columns: ['mean_score'] } };
    const renderer = createEntityTableViewRenderer();
    const instance = await renderer.render(view as never,
      { table: [{ path: 'scores.csv', size: 10, sha256: 'a'.repeat(64), url: '/artifacts/s', table_url: '/tables/s' }] } as never,
      host as unknown as HTMLElement, { signal: new AbortController().signal, taskId: 'a'.repeat(32) });
    const table = host.querySelector('table.entity-result-table')!;
    expect(table.querySelectorAll('th').map((cell) => cell.textContent)).toEqual(['mutation', 'mean_score']);
    expect(table.querySelectorAll('tr')).toHaveLength(4);
    (instance as { destroy(): void }).destroy();
    expect(host.querySelector('table')).toBeNull();
  });

  it('states that a table larger than the bounded window was truncated', async () => {
    installHarness(vi.stubGlobal);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      columns: ['mutation', 'mean_score'], rows: [['A1V', '1']], offset: 0, limit: 500, has_more: true,
    }), { status: 200 })));
    const host = document.createElement('section') as unknown as HarnessNode;
    const view = { id: 'mutation_scores', plugin: 'entity-table', role: 'primary', title: 'Scores',
      sources: { table: ['scores.csv'] }, mapping: { key_columns: ['mutation'], evidence_columns: ['mean_score'] } };
    await createEntityTableViewRenderer().render(view as never,
      { table: [{ path: 'scores.csv', size: 10, sha256: 'a'.repeat(64), url: '/artifacts/s', table_url: '/tables/s' }] } as never,
      host as unknown as HTMLElement, { signal: new AbortController().signal, taskId: 'a'.repeat(32) });
    expect(host.textContent).toContain('larger than the bounded preview');
  });

  it('draws one path per declared value column and labels the chart with the declared axes', async () => {
    installHarness(vi.stubGlobal);
    servePages([['1', '-2.5', '0.4'], ['2', '-2.0', '0.3'], ['3', '-1.5', '0.2']], ['position', 'log_prob', 'entropy'], 500);
    const host = document.createElement('section') as unknown as HarnessNode;
    const view = { id: 'residue_profile', plugin: 'metric-series', role: 'primary', title: 'Residue profile',
      sources: { series: ['msa1b_profile.csv'] },
      mapping: { format: 'csv', x_column: 'position', value_columns: ['log_prob', 'entropy'],
        x_label: 'Residue position', y_label: 'Model value', unit: 'natural log units', direction: 'neutral' } };
    const renderer = createMetricSeriesViewRenderer();
    await renderer.render(view as never,
      { series: [{ path: 'msa1b_profile.csv', size: 10, sha256: 'a'.repeat(64), url: '/artifacts/p', table_url: '/tables/p' }] } as never,
      host as unknown as HTMLElement, { signal: new AbortController().signal, taskId: 'a'.repeat(32) });
    expect(host.querySelectorAll('svg path')).toHaveLength(2);
    expect(host.querySelectorAll('.metric-series-legend li').map((item) => item.textContent))
      .toEqual(['log_prob · 3 values', 'entropy · 3 values']);
    expect(host.textContent).toContain('Model value · natural log units');
  });

  it('plots a declared JSON value path instead of asking for a table page', async () => {
    installHarness(vi.stubGlobal);
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      urls.push(url);
      return new Response(JSON.stringify({ confidenceScore: [91.5, 87, null, 62.25] }), { status: 200 });
    }));
    const host = document.createElement('section') as unknown as HarnessNode;
    const view = { id: 'residue_confidence', plugin: 'metric-series', role: 'evidence', title: 'Per-residue model confidence',
      sources: { series: ['rank_1/confidence_model_1.json'] },
      mapping: { format: 'json', value_path: 'confidenceScore', x_label: 'Residue position', y_label: 'pLDDT',
        unit: 'score', direction: 'higher', y_min: 0, y_max: 100 } };
    await createMetricSeriesViewRenderer().render(view as never,
      { series: [{ path: 'rank_1/confidence_model_1.json', size: 512, sha256: 'a'.repeat(64),
        url: '/artifacts/rank_1/confidence_model_1.json' }] } as never,
      host as unknown as HTMLElement, { signal: new AbortController().signal, taskId: 'a'.repeat(32) });
    expect(urls).toEqual(['/artifacts/rank_1/confidence_model_1.json']);
    expect(host.querySelectorAll('svg path')).toHaveLength(1);
    expect(host.textContent).toContain('pLDDT');
  });

  it('refuses a JSON value path that does not resolve to a numeric list', async () => {
    installHarness(vi.stubGlobal);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ confidenceScore: 'high' }), { status: 200 })));
    const view = { id: 'residue_confidence', plugin: 'metric-series', role: 'evidence', title: 'Confidence',
      sources: { series: ['confidence.json'] }, mapping: { format: 'json', value_path: 'confidenceScore' } };
    await expect(createMetricSeriesViewRenderer().render(view as never,
      { series: [{ path: 'confidence.json', size: 20, sha256: 'a'.repeat(64), url: '/a/confidence.json' }] } as never,
      document.createElement('section') as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32) })).rejects.toThrow('not a list');
  });

  it('states the reason a declared column is missing instead of plotting another one', async () => {
    installHarness(vi.stubGlobal);
    servePages([['1', '-2.5']], ['position', 'log_prob'], 500);
    const view = { id: 'residue_profile', plugin: 'metric-series', role: 'primary', title: 'Profile',
      sources: { series: ['profile.csv'] }, mapping: { x_column: 'position', value_columns: ['entropy'] } };
    await expect(createMetricSeriesViewRenderer().render(view as never,
      { series: [{ path: 'profile.csv', size: 1, sha256: 'a'.repeat(64), url: '/a', table_url: '/tables/p' }] } as never,
      document.createElement('section') as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32) })).rejects.toThrow();
  });
});
