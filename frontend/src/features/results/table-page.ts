/*
 * Bounded table paging shared by the `entity-table` and `metric-series` view renderers.
 *
 * The Server serves a published table through one route with a hard `limit` ceiling and a
 * bounded `offset` window; this loader walks that window instead of asking for an unbounded
 * response, so a large published table fails with a stated reason rather than exhausting
 * browser memory. A local result has no route, so the same loader reads the same page from
 * the opened folder through one parser that enforces the route's own bounds, in slices, so a
 * large CSV is never materialised. It reads only the rows the page returns and never infers
 * meaning from a filename: column names come from the page header and the mapping the Task
 * declared.
 */
import { isLogicalFile, type ResultFile } from '../../api/result-types';
import { t } from '../../app/i18n';
import type { LocalSourceFiles } from './renderer-registry';

/** The route refuses `limit` above 500 and `offset` above 10000. */
export const PAGE_LIMIT = 500;
export const MAX_OFFSET = 10_000;
/** The route's column cap, and the wider one a `matrix=1` page may use for value columns. */
export const MAX_COLUMNS = 100;
export const MATRIX_MAX_COLUMNS = 512 + 1;
export const MAX_CELL_BYTES = 16 * 1024;
export const MAX_PAGE_BYTES = 8 * 1024 * 1024;
const PAGE_ENVELOPE_BYTES = 512;
/** A local file is decoded in bounded slices, never as one whole string. */
const CHUNK_BYTES = 256 * 1024;

export interface TablePage {
  columns: string[];
  rows: string[][];
}

export interface TablePageResponse extends TablePage {
  offset: number;
  limit: number;
  has_more: boolean;
}

interface RawPage {
  columns?: unknown;
  rows?: unknown;
  has_more?: boolean;
}

/** One resolved view source's table read: the Server's bounded route, or the opened local folder. */
export type TableRead = string | LocalTableRead;

export interface LocalTableRead {
  readonly files: LocalSourceFiles;
  readonly source: ResultFile | undefined;
}

/** The bounded table URL of one resolved source, or `undefined` when it has none. */
export function tableUrlOf(source: ResultFile | undefined, taskId: string): string | undefined {
  if (!source) return undefined;
  if (source.table_url) return source.table_url;
  // A logical file carries the Server's bounded table URL or nothing: its path is
  // published identity, not a route the browser may construct.
  if (isLogicalFile(source)) return undefined;
  const encoded = source.path.split('/').map(encodeURIComponent).join('/');
  return `/compute/api/results/${encodeURIComponent(taskId)}/tables/${encoded}`;
}

/**
 * The local read when a local source is open, else `undefined`.
 *
 * A view that receives one never composes a Server URL from an archived `task_id`: the local
 * source resolves to the opened folder's own file, and a file that is not there is stated as
 * missing rather than asked for remotely.
 */
export function localTableRead(files: LocalSourceFiles | undefined, source: ResultFile | undefined): LocalTableRead | undefined {
  return files ? { files, source } : undefined;
}

/**
 * Page one table up to `maxRows` rows.
 *
 * Every page is validated against the first page's header, so a source that changes its shape
 * mid-walk is reported instead of silently mixing columns. `has_more` on the final accepted
 * page is reported so a caller can state that the view is truncated.
 */
export async function loadTable(
  read: TableRead | undefined,
  options: { signal?: AbortSignal; maxRows?: number } = {},
): Promise<{ page: TablePage; truncated: boolean }> {
  if (!read) throw new TypeError(t('results.table.error.noUrl'));
  const maximum = options.maxRows ?? MAX_OFFSET + PAGE_LIMIT;
  let columns: string[] | null = null;
  const rows: string[][] = [];
  let offset = 0;
  for (;;) {
    const query = new URLSearchParams({ offset: String(offset), limit: String(PAGE_LIMIT) });
    const page = await readTablePage(read, query, options.signal) as RawPage;
    if (!Array.isArray(page.columns) || !page.columns.length || !Array.isArray(page.rows)) {
      throw new Error(t('results.table.error.malformed'));
    }
    const header = page.columns.map(String);
    if (columns === null) columns = header;
    if (header.length !== columns.length || page.rows.some((row) => !Array.isArray(row) || row.length !== columns!.length)) {
      throw new Error(t('results.table.error.malformed'));
    }
    rows.push(...page.rows.map((row) => (row as unknown[]).map((cell) => String(cell ?? ''))));
    if (!page.has_more) return { page: { columns, rows }, truncated: false };
    if (!page.rows.length) throw new Error(t('results.table.error.malformed'));
    offset += page.rows.length;
    if (offset >= maximum || offset > MAX_OFFSET) return { page: { columns, rows }, truncated: true };
  }
}

/** One column's cells, erroring when the column the Task declared is absent. */
export function column(page: TablePage, name: string): string[] {
  const index = page.columns.indexOf(name);
  if (index < 0) throw new Error(t('results.table.error.missingColumn', { column: name }));
  return page.rows.map((row) => row[index] ?? '');
}

/**
 * Read one page from the route or the local folder, so every view loader shares one read.
 *
 * The query is the same either way; only transport differs, and a local file's page is built
 * by the same parser with the same bounds.
 */
export async function readTablePage(
  read: TableRead,
  query: URLSearchParams,
  signal?: AbortSignal,
  failure = t('results.table.error.pageLoad'),
): Promise<unknown> {
  if (typeof read !== 'string') {
    return readLocalTablePage(read.files, read.source, {
      offset: Number(query.get('offset')),
      limit: Number(query.get('limit')),
      matrix: query.get('matrix') === '1',
    }, signal);
  }
  const base = read.includes('?') ? `${read}&` : `${read}?`;
  const response = await fetch(`${base}${query}`, { credentials: 'same-origin', signal });
  if (!response.ok) throw new Error(failure);
  return await response.json();
}

export interface LocalPageQuery {
  offset: number;
  limit: number;
  matrix?: boolean;
}

/**
 * Read one bounded page from a resolved local table file with the Server route's semantics:
 * the same offset/limit bounds, delimiter choice, column cap, cell and page byte budgets, and
 * response shape. Parsing stops at the page's last needed row, so only the bytes the page
 * needs are read.
 */
export async function readLocalTablePage(
  files: LocalSourceFiles,
  source: ResultFile | undefined,
  query: LocalPageQuery,
  signal?: AbortSignal,
): Promise<TablePageResponse> {
  const { offset, limit } = query;
  if (!Number.isInteger(offset) || offset < 0 || offset > MAX_OFFSET || !Number.isInteger(limit) || limit < 1 || limit > PAGE_LIMIT) {
    throw new Error(t('results.local.table.bounds'));
  }
  if (!source) throw new Error(t('results.local.table.missing'));
  const file = files.file(source.path);
  if (!file) throw new Error(t('results.local.table.missing'));
  const delimiter = source.path.toLowerCase().endsWith('.tsv') ? '\t' : ',';
  const maxColumns = query.matrix ? MATRIX_MAX_COLUMNS : MAX_COLUMNS;
  let columns: string[] | null = null;
  let pageBytes = 0;
  const rows: string[][] = [];
  let skipped = 0;
  let hasMore = false;
  for await (const row of readRecords(file, delimiter, maxColumns, signal)) {
    if (columns === null) {
      pageBytes = PAGE_ENVELOPE_BYTES + rowCost(row);
      if (pageBytes > MAX_PAGE_BYTES) throw new Error(t('results.local.table.pageTooLarge'));
      columns = row;
      continue;
    }
    if (skipped < offset) { skipped += 1; continue; }
    if (rows.length === limit) { hasMore = true; break; }
    const cost = rowCost(row);
    if (pageBytes + cost > MAX_PAGE_BYTES) throw new Error(t('results.local.table.pageTooLarge'));
    pageBytes += cost;
    rows.push(row);
  }
  return { columns: columns ?? [], rows, offset, limit, has_more: hasMore };
}

const ASCII = /^[\x00-\x7f]*$/;

/**
 * The route's per-row cost: separators plus each cell's `ensure_ascii` JSON bytes.
 *
 * The cell and column ceilings are enforced by `readRecords` as it accumulates, so a row that
 * reaches this function is already inside both — including a row the page skips by `offset`,
 * which never reaches this function at all and must still be refused.
 */
function rowCost(row: string[]): number {
  let cost = 2 + Math.max(0, row.length - 1);
  for (const cell of row) {
    const json = JSON.stringify(cell);
    if (ASCII.test(json)) { cost += json.length; continue; }
    for (const char of json) cost += char.codePointAt(0)! < 0x80 ? 1 : char.codePointAt(0)! < 0x10000 ? 6 : 12;
  }
  return cost;
}

/**
 * Yield the records of one delimited file, decoding bounded slices so no read is unbounded.
 *
 * The grammar is the Server's `csv` reader: a quoted field may hold the delimiter, a newline,
 * or a doubled quote, and text after its closing quote continues the field; records end at
 * `\r\n`, `\r`, or `\n`; a blank line is one empty record. A quote that never closes is
 * malformed rather than guessed.
 *
 * The route's cell and column ceilings are enforced while a field and a row are built, not
 * after the record is complete: the file is untrusted, an unterminated quote or one long
 * unbroken field would otherwise accumulate the whole file before any check ran, and a row
 * the page skips by `offset` never reaches a later check at all.
 */
type FieldState = 'start' | 'text' | 'quoted' | 'closed';

/** The UTF-8 length of one decoded code point, as `TextEncoder` would encode it. */
function utf8Length(char: string): number {
  const point = char.codePointAt(0)!;
  return point < 0x80 ? 1 : point < 0x800 ? 2 : point < 0x10000 ? 3 : 4;
}

async function* readRecords(file: Blob, delimiter: string, maxColumns: number, signal?: AbortSignal): AsyncGenerator<string[]> {
  const decoder = new TextDecoder('utf-8', { fatal: true });
  let field = '';
  // The encoded bytes of `field` so far, so the ceiling costs one addition per character
  // instead of a re-encode of the whole field.
  let fieldBytes = 0;
  let row: string[] = [];
  // 'start' of a field, plain 'text', inside a quoted field, or just past its closing quote.
  let state: FieldState = 'start';
  let skipLF = false;

  const append = (text: string): void => {
    for (const char of text) fieldBytes += utf8Length(char);
    if (fieldBytes > MAX_CELL_BYTES) throw new Error(t('results.local.table.cellTooLarge'));
    field += text;
  };
  const endField = (): void => {
    if (row.length >= maxColumns) throw new Error(t('results.local.table.tooWide'));
    row.push(field); field = ''; fieldBytes = 0; state = 'start';
  };
  const endRecord = (): string[] => {
    // A blank line is an empty record, as the Server's `csv` reader reports it.
    const record = state === 'closed' || row.length || field !== '' ? [...row, field] : [];
    if (record.length > maxColumns) throw new Error(t('results.local.table.tooWide'));
    row = []; field = ''; fieldBytes = 0; state = 'start';
    return record;
  };

  function* feed(text: string): Generator<string[]> {
    for (const char of text) {
      if (skipLF) { skipLF = false; if (char === '\n') continue; }
      if (state === 'quoted') {
        if (char === '"') state = 'closed'; else append(char);
        continue;
      }
      if (state === 'closed') {
        if (char === '"') { append('"'); state = 'quoted'; continue; }
        if (char === delimiter) { endField(); continue; }
        if (char === '\r') skipLF = true; else if (char !== '\n') { append(char); state = 'text'; continue; }
        yield endRecord();
        continue;
      }
      if (char === '"' && state === 'start') { state = 'quoted'; continue; }
      if (char === delimiter) { endField(); continue; }
      if (char === '\r') skipLF = true;
      if (char === '\r' || char === '\n') { yield endRecord(); continue; }
      append(char); state = 'text';
    }
  }

  const decode = (buffer: ArrayBuffer, stream: boolean): string => {
    try { return decoder.decode(buffer, { stream }); } catch { throw new Error(t('results.local.table.encoding')); }
  };
  for (let start = 0; start < file.size; start += CHUNK_BYTES) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const buffer = await file.slice(start, Math.min(start + CHUNK_BYTES, file.size)).arrayBuffer();
    yield* feed(decode(buffer, true));
  }
  yield* feed(decode(new ArrayBuffer(0), false));
  // `feed` owns every state transition; the casts keep flow analysis from treating the
  // state as the value this scope last saw.
  if ((state as FieldState) === 'quoted') throw new Error(t('results.local.table.malformed'));
  if (row.length || field !== '' || (state as FieldState) === 'closed') yield endRecord();
}
