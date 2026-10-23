import { describe, expect, it, vi } from 'vitest';

import { createMetricSeriesViewRenderer } from '../src/features/results/metric-series-view';
import { createEntityTableViewRenderer } from '../src/features/results/entity-table-view';
import { createMatrixViewRenderer, loadMatrixSeries } from '../src/features/results/matrix-view';
import type { LocalSourceFiles } from '../src/features/results/renderer-registry';
import {
  loadTable, localTableRead, MAX_CELL_BYTES, MAX_COLUMNS, MAX_OFFSET, MATRIX_MAX_COLUMNS, PAGE_LIMIT,
  readLocalTablePage, tableUrlOf,
} from '../src/features/results/table-page';
import { installHarness } from './dom-harness';

/*
 * Local table reads: one parser, the Server route's semantics.
 *
 * The Server's bounded table route is the contract (offset ≤ 10000, limit ≤ 500, `\t` for
 * `.tsv` and `,` otherwise, 100 columns or 513 for a matrix page, 16 KiB cells, an 8 MiB
 * page). A local result has no route, so these tests drive the same loader over an opened
 * folder and assert the same page, and that no local read ever composes a Server URL.
 */

/** A local folder of in-memory files, implementing the Source Owner's `LocalSourceFiles`. */
function localFolder(entries: Record<string, string>): LocalSourceFiles & { reads: string[] } {
  const reads: string[] = [];
  return {
    label: 'opened folder',
    reads,
    file: (path) => Object.hasOwn(entries, path) ? new File([entries[path]!], path, { type: 'text/csv' }) : null,
    readUtf8: async (path, maxBytes) => {
      reads.push(path);
      if (!Object.hasOwn(entries, path)) throw new Error('The local result folder does not contain this file.');
      const text = entries[path]!;
      if (new TextEncoder().encode(text).length > maxBytes) throw new Error('The local file exceeds the read limit.');
      return text;
    },
  };
}

const source = (path: string) => ({ path, size: 1, sha256: 'a'.repeat(64), url: `blob:local/${path}` }) as never;

function csv(rows: string[][], delimiter = ','): string {
  return rows.map((row) => row.join(delimiter)).join('\n');
}

describe('local table paging', () => {
  it('pages a local CSV with the Server route\'s bounds and response shape', async () => {
    const files = localFolder({ 'couplings/raw_scores.csv': `position,1,2\n${'1,0,1\n2,1,0'}` });
    const first = await readLocalTablePage(files, source('couplings/raw_scores.csv'), { offset: 0, limit: 1 });
    expect(first).toEqual({ columns: ['position', '1', '2'], rows: [['1', '0', '1']], offset: 0, limit: 1, has_more: true });
    const second = await readLocalTablePage(files, source('couplings/raw_scores.csv'), { offset: 1, limit: 1 });
    expect(second).toEqual({ columns: ['position', '1', '2'], rows: [['2', '1', '0']], offset: 1, limit: 1, has_more: false });
  });

  it('walks a local table through loadTable exactly as it walks the route', async () => {
    const rows = Array.from({ length: 1201 }, (_, index) => [`row${index}`, String(index)]);
    const files = localFolder({ 'scores.csv': csv([['name', 'score'], ...rows]) });
    const { page, truncated } = await loadTable(localTableRead(files, source('scores.csv')));
    expect(page.columns).toEqual(['name', 'score']);
    expect(page.rows).toHaveLength(1201);
    expect(page.rows[1200]).toEqual(['row1200', '1200']);
    expect(truncated).toBe(false);
  });

  it('reports the last page as truncated when the walk reaches the row window', async () => {
    // The window is `offset ≤ 10000` plus one page: a longer table stops there.
    const rows = Array.from({ length: MAX_OFFSET + PAGE_LIMIT + 10 }, (_, index) => [`r${index}`]);
    const files = localFolder({ 'scores.csv': csv([['name'], ...rows]) });
    const { page, truncated } = await loadTable(localTableRead(files, source('scores.csv')));
    expect(page.rows).toHaveLength(MAX_OFFSET + PAGE_LIMIT);
    expect(truncated).toBe(true);
  });

  it('chooses the delimiter from the file\'s own path, as the route does', async () => {
    const files = localFolder({
      'pairwise_scores.tsv': 'chain,residue\tscore\nA\t1.5',
      'pairwise_scores.csv': 'chain,residue\tscore\nA\t1.5',
    });
    const tsv = await readLocalTablePage(files, source('pairwise_scores.tsv'), { offset: 0, limit: 10 });
    expect(tsv.columns).toEqual(['chain,residue', 'score']);
    expect(tsv.rows).toEqual([['A', '1.5']]);
    // The same bytes under `.csv` are one comma-separated field, not a guess.
    const csvPage = await readLocalTablePage(files, source('pairwise_scores.csv'), { offset: 0, limit: 10 });
    expect(csvPage.columns).toEqual(['chain', 'residue\tscore']);
  });

  it('reads a quoted field holding the delimiter, a newline, and a doubled quote', async () => {
    const files = localFolder({ 'notes.csv': 'name,note\n"a,b","line one\nline ""two"""' });
    const page = await readLocalTablePage(files, source('notes.csv'), { offset: 0, limit: 10 });
    expect(page.rows).toEqual([['a,b', 'line one\nline "two"']]);
  });

  it('reports a row whose width changes when it is paged, keeping the header stable', async () => {
    const files = localFolder({ 'wide.csv': 'a,b\n1,2\n3\n' });
    await expect(loadTable(localTableRead(files, source('wide.csv')))).rejects.toThrow('malformed');
  });

  it('refuses a page outside the route\'s offset and limit bounds', async () => {
    const files = localFolder({ 'scores.csv': 'a\n1' });
    for (const query of [{ offset: -1, limit: 1 }, { offset: MAX_OFFSET + 1, limit: 1 },
      { offset: 0, limit: 0 }, { offset: 0, limit: PAGE_LIMIT + 1 }, { offset: 0.5, limit: 1 }]) {
      await expect(readLocalTablePage(files, source('scores.csv'), query))
        .rejects.toThrow('outside the allowed bounds');
    }
    await expect(readLocalTablePage(files, source('scores.csv'), { offset: 0, limit: PAGE_LIMIT })).resolves.toBeDefined();
    await expect(readLocalTablePage(files, source('scores.csv'), { offset: MAX_OFFSET, limit: 1 })).resolves.toBeDefined();
  });

  it('caps columns at 513 for a matrix page and 100 for a table page', async () => {
    const wide = Array.from({ length: MATRIX_MAX_COLUMNS }, (_, index) => `c${index}`);
    const row = wide.map((_, index) => String(index));
    const files = localFolder({ 'm.csv': csv([wide, row]) });
    await expect(readLocalTablePage(files, source('m.csv'), { offset: 0, limit: 10 })).rejects.toThrow('more columns');
    const matrix = await readLocalTablePage(files, source('m.csv'), { offset: 0, limit: 10, matrix: true });
    expect(matrix.columns).toHaveLength(MATRIX_MAX_COLUMNS);
    expect(matrix.columns).toHaveLength(MAX_COLUMNS + 413);
  });

  it('refuses a cell above 16 KiB rather than truncating it', async () => {
    const oversized = 'x'.repeat(MAX_CELL_BYTES + 1);
    const files = localFolder({ 'cells.csv': `a,b\nok,${oversized}` });
    await expect(readLocalTablePage(files, source('cells.csv'), { offset: 0, limit: 10 }))
      .rejects.toThrow('exceeds the 16 KiB preview limit');
  });

  it('refuses an oversized cell while it is being read, not after the whole file', async () => {
    // Five megabytes of one unbroken field: nothing but the accumulation itself bounds it, so
    // the refusal has to come from the parser as it appends, before the file is read whole.
    const text = `a,b\n${'x'.repeat(5 * 1024 * 1024)}`;
    const file = new File([text], 'long-cell.csv');
    const read: number[] = [];
    const slice = file.slice.bind(file);
    Object.defineProperty(file, 'slice', {
      value: (start?: number, end?: number) => {
        const part = slice(start, end);
        const arrayBuffer = part.arrayBuffer.bind(part);
        Object.defineProperty(part, 'arrayBuffer', {
          value: () => { read.push((end ?? 0) - (start ?? 0)); return arrayBuffer(); },
        });
        return part;
      },
    });
    const files: LocalSourceFiles = { label: 'long', file: () => file, readUtf8: async () => { throw new Error('not used'); } };
    await expect(readLocalTablePage(files, source('long-cell.csv'), { offset: 0, limit: 10 }))
      .rejects.toThrow('exceeds the 16 KiB preview limit');
    expect(read.reduce((total, bytes) => total + bytes, 0)).toBeLessThanOrEqual(256 * 1024);
  });

  it('refuses an unterminated quote that runs past the cell cap instead of buffering it', async () => {
    const text = `a,b\n"${'y'.repeat(5 * 1024 * 1024)}`;
    const files = localFolder({ 'open.csv': text });
    await expect(readLocalTablePage(files, source('open.csv'), { offset: 0, limit: 10 }))
      .rejects.toThrow('exceeds the 16 KiB preview limit');
    // A short unterminated quote is still reported as malformed, as before.
    const short = localFolder({ 'short.csv': 'a,b\n"open,2\n' });
    await expect(readLocalTablePage(short, source('short.csv'), { offset: 0, limit: 10 }))
      .rejects.toThrow('malformed');
  });

  it('bounds a row the page skips by offset, which no later check would see', async () => {
    const oversizedRow = `x,${'z'.repeat(MAX_CELL_BYTES + 1)}\n`;
    const files = localFolder({ 'skip.csv': `a,b\n${oversizedRow}1,2\n` });
    await expect(readLocalTablePage(files, source('skip.csv'), { offset: 1, limit: 1 }))
      .rejects.toThrow('exceeds the 16 KiB preview limit');
    const wideRow = `${Array.from({ length: MAX_COLUMNS + 1 }, () => '0').join(',')}\n`;
    const wide = localFolder({ 'skip.csv': `a,b\n${wideRow}1,2\n` });
    await expect(readLocalTablePage(wide, source('skip.csv'), { offset: 1, limit: 1 }))
      .rejects.toThrow('more columns');
  });

  it('reads a record whose quoted field crosses a slice boundary', async () => {
    // 100 bounded cells put the closing quoted cell beyond the first 256 KiB slice.
    const cells = Array.from({ length: MAX_COLUMNS - 1 }, () => 'p'.repeat(4000));
    const files = localFolder({ 'split.csv': `a,b\n${cells.join(',')},"trailing,quote"\n` });
    const page = await readLocalTablePage(files, source('split.csv'), { offset: 0, limit: 1 });
    expect(page.rows[0]).toHaveLength(MAX_COLUMNS);
    expect(page.rows[0]!.at(-1)).toBe('trailing,quote');
  });

  it('refuses a page above 8 MiB rather than returning a partial page', async () => {
    // A wide page at the cell cap: 16 columns of 16 KB cells, 33 rows ≈ 8.4 MiB.
    const header = Array.from({ length: 16 }, (_, index) => `c${index}`);
    const cell = 'y'.repeat(16_000);
    const rows = Array.from({ length: 33 }, () => Array.from({ length: 16 }, () => cell));
    const files = localFolder({ 'big.csv': csv([header, ...rows]) });
    await expect(readLocalTablePage(files, source('big.csv'), { offset: 0, limit: 500 }))
      .rejects.toThrow('exceeds the 8 MiB preview limit');
  });

  it('reads only the slices its page needs, never the whole file', async () => {
    const rows = Array.from({ length: 200_000 }, (_, index) => `r${index},${index}`);
    const text = `name,value\n${rows.join('\n')}`;
    const file = new File([text], 'long.csv');
    const sliced: number[] = [];
    const slice = file.slice.bind(file);
    Object.defineProperty(file, 'slice', {
      value: (start?: number, end?: number) => {
        const part = slice(start, end);
        const arrayBuffer = part.arrayBuffer.bind(part);
        Object.defineProperty(part, 'arrayBuffer', {
          value: () => { sliced.push((end ?? 0) - (start ?? 0)); return arrayBuffer(); },
        });
        return part;
      },
    });
    const files: LocalSourceFiles = { label: 'long', file: () => file, readUtf8: async () => { throw new Error('not used'); } };
    const page = await readLocalTablePage(files, source('long.csv'), { offset: 0, limit: 2 });
    expect(page.rows).toHaveLength(2);
    // The first slice alone covers two rows; the multi-megabyte file is never read whole.
    expect(Math.max(...sliced)).toBeLessThanOrEqual(256 * 1024);
    expect(sliced.reduce((total, bytes) => total + bytes, 0)).toBeLessThan(file.size);
  });

  it('states a missing local file, a malformed quote, and an invalid encoding', async () => {
    const files = localFolder({ 'scores.csv': 'a\n1' });
    await expect(readLocalTablePage(files, source('missing.csv'), { offset: 0, limit: 10 }))
      .rejects.toThrow('does not contain this table');
    await expect(readLocalTablePage(files, undefined, { offset: 0, limit: 10 }))
      .rejects.toThrow('does not contain this table');
    const unterminated = localFolder({ 'q.csv': 'a,b\n"open,2\n' });
    await expect(readLocalTablePage(unterminated, source('q.csv'), { offset: 0, limit: 10 }))
      .rejects.toThrow('malformed');
    // Text after a closing quote continues the field, as the Server's reader parses it.
    const trailing = localFolder({ 'q.csv': 'a,b\n"x"y,2\n' });
    expect((await readLocalTablePage(trailing, source('q.csv'), { offset: 0, limit: 10 })).rows).toEqual([['xy', '2']]);
    const invalid = localFolder({});
    const bad = new File([new Uint8Array([0x61, 0xff, 0x0a])], 'bad.csv');
    const invalidFolder: LocalSourceFiles = { label: 'bad', file: () => bad, readUtf8: invalid.readUtf8 };
    await expect(readLocalTablePage(invalidFolder, source('bad.csv'), { offset: 0, limit: 10 }))
      .rejects.toThrow('not valid UTF-8');
  });

  it('propagates abort instead of finishing a page', async () => {
    const files = localFolder({ 'scores.csv': 'a\n1\n' });
    const controller = new AbortController(); controller.abort();
    await expect(readLocalTablePage(files, source('scores.csv'), { offset: 0, limit: 10 }, controller.signal))
      .rejects.toHaveProperty('name', 'AbortError');
  });

  it('treats a blank line as one empty record, as the Server\'s csv reader does', async () => {
    const files = localFolder({ 'blank.csv': 'a,b\n1,2\n\n3,4\n' });
    const page = await readLocalTablePage(files, source('blank.csv'), { offset: 0, limit: 10 });
    // A blank record is one empty field; narrowing it is the loader's own width check.
    expect(page.rows).toEqual([['1', '2'], [], ['3', '4']]);
    await expect(loadTable(localTableRead(files, source('blank.csv')))).rejects.toThrow('malformed');
  });

  it('never yields a Server URL for a local source', () => {
    const files = localFolder({});
    const artifact = { path: 'nested dir/scores.csv', url: 'blob:local/scores' } as never;
    expect(tableUrlOf(artifact, 'a'.repeat(32))).toContain('/compute/api/');
    expect(tableUrlOf(artifact, 'a'.repeat(32))).toContain('nested%20dir');
    const read = localTableRead(files, artifact)!;
    expect(read).toEqual({ files, source: artifact });
    expect(localTableRead(undefined, artifact)).toBeUndefined();
  });
});

describe('local views read the opened folder, not the Server', () => {
  const fetchSpy = () => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url);
      return new Response('{"error":"local source asked the server"}', { status: 500 });
    }));
    return calls;
  };

  it('pages a local matrix through the same loader the matrix view uses', async () => {
    const calls = fetchSpy();
    const files = localFolder({ 'couplings/apc_scores.csv': 'position,1,2\n1,0,-2\n2,-2,0' });
    const series = await loadMatrixSeries(localTableRead(files, source('couplings/apc_scores.csv')), { row_labels_column: 'position' });
    expect(series).toEqual({ values: [[0, -2], [-2, 0]], xLabels: ['1', '2'], yLabels: ['1', '2'] });
    expect(calls).toEqual([]);
  });

  it('states a missing local table from the matrix view instead of asking the Server for it', async () => {
    const calls = fetchSpy();
    installHarness(vi.stubGlobal);
    const files = localFolder({});
    const view = {
      id: 'apc', plugin: 'matrix', role: 'primary', title: 'APC', sources: { matrices: ['couplings/apc_scores.csv'] },
      mapping: {},
    };
    await expect(createMatrixViewRenderer().render(view as never,
      { matrices: [{ ...(source('couplings/apc_scores.csv') as object), table_url: '/compute/api/results/x/tables/y' }] } as never,
      document.createElement('section') as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32), localSource: files }))
      .rejects.toThrow('does not contain this table');
    expect(calls).toEqual([]);
  });

  it('renders an entity table from a local TSV and never composes a table route', async () => {
    const calls = fetchSpy();
    installHarness(vi.stubGlobal);
    const files = localFolder({
      'couplings/pairwise_scores.tsv': 'i\tj\tscore\tchain\n1\t2\t0.9\tA',
    });
    const view = {
      id: 'pairs', plugin: 'entity-table', role: 'primary', title: 'Pairs',
      sources: { table: ['couplings/pairwise_scores.tsv'] },
      mapping: { key_columns: ['i', 'j'], evidence_columns: ['score'] },
    };
    const host = document.createElement('section');
    await createEntityTableViewRenderer().render(view as never,
      { table: [source('couplings/pairwise_scores.tsv')] } as never, host,
      { signal: new AbortController().signal, taskId: 'b'.repeat(32), localSource: files });
    expect(calls).toEqual([]);
    expect((host as unknown as { querySelectorAll(selector: string): Array<{ textContent: string }> })
      .querySelectorAll('th').map((cell) => cell.textContent)).toEqual(['i', 'j', 'score']);
  });

  it('plots a local JSON series through the folder\'s text read, not fetch(blob:)', async () => {
    const calls = fetchSpy();
    installHarness(vi.stubGlobal);
    const files = localFolder({ 'rank_1/confidence_model_1.json': '{"confidenceScore":[91.5,87,null]}' });
    const view = {
      id: 'confidence', plugin: 'metric-series', role: 'evidence', title: 'Confidence',
      sources: { series: ['rank_1/confidence_model_1.json'] },
      mapping: { format: 'json', value_path: 'confidenceScore', y_label: 'pLDDT' },
    };
    const host = document.createElement('section');
    await createMetricSeriesViewRenderer().render(view as never,
      { series: [{ ...(source('rank_1/confidence_model_1.json') as object), size: 512 }] } as never, host,
      { signal: new AbortController().signal, taskId: 'c'.repeat(32), localSource: files });
    expect(calls).toEqual([]);
    expect(files.reads).toEqual(['rank_1/confidence_model_1.json']);
    expect(host.querySelectorAll('svg path')).toHaveLength(1);
  });

  it('states a local JSON file the folder cannot read', async () => {
    const calls = fetchSpy();
    installHarness(vi.stubGlobal);
    const files = localFolder({});
    const view = {
      id: 'confidence', plugin: 'metric-series', role: 'evidence', title: 'Confidence',
      sources: { series: ['confidence.json'] }, mapping: { format: 'json', value_path: 'confidenceScore' },
    };
    await expect(createMetricSeriesViewRenderer().render(view as never,
      { series: [{ ...(source('confidence.json') as object), size: 20 }] } as never,
      document.createElement('section'),
      { signal: new AbortController().signal, taskId: 'c'.repeat(32), localSource: files }))
      .rejects.toThrow('does not contain this file');
    expect(calls).toEqual([]);
  });
});
