/*
 * Bounded table paging shared by the `entity-table` and `metric-series` view renderers.
 *
 * The Server serves a published table through one route with a hard `limit` ceiling and a
 * bounded `offset` window; this loader walks that window instead of asking for an unbounded
 * response, so a large published table fails with a stated reason rather than exhausting
 * browser memory. It reads only the rows the route returns and never infers meaning from a
 * filename: column names come from the page header and the mapping the Task declared.
 */
import type { ResultFile } from '../../api/result-types';
import { t } from '../../app/i18n';

/** The route refuses `limit` above 500 and `offset` above 10000. */
export const PAGE_LIMIT = 500;
export const MAX_OFFSET = 10_000;

export interface TablePage {
  columns: string[];
  rows: string[][];
}

interface RawPage {
  columns?: unknown;
  rows?: unknown;
  has_more?: boolean;
}

/** The bounded table URL of one resolved source, or `undefined` when it has none. */
export function tableUrlOf(source: ResultFile | undefined, taskId: string): string | undefined {
  if (!source) return undefined;
  if (source.table_url) return source.table_url;
  if (!('path' in source)) return undefined;
  const encoded = source.path.split('/').map(encodeURIComponent).join('/');
  return `/compute/api/results/${encodeURIComponent(taskId)}/tables/${encoded}`;
}

/**
 * Page one published table up to `maxRows` rows.
 *
 * Every page is validated against the first page's header, so a route that changes its shape
 * mid-walk is reported instead of silently mixing columns. `has_more` on the final accepted
 * page is reported so a caller can state that the view is truncated.
 */
export async function loadTable(
  tableUrl: string | undefined,
  options: { signal?: AbortSignal; maxRows?: number } = {},
): Promise<{ page: TablePage; truncated: boolean }> {
  if (!tableUrl) throw new TypeError(t('results.table.error.noUrl'));
  const maximum = options.maxRows ?? MAX_OFFSET + PAGE_LIMIT;
  const base = tableUrl.includes('?') ? `${tableUrl}&` : `${tableUrl}?`;
  let columns: string[] | null = null;
  const rows: string[][] = [];
  let offset = 0;
  for (;;) {
    const query = new URLSearchParams({ offset: String(offset), limit: String(PAGE_LIMIT) });
    const response = await fetch(`${base}${query}`, { credentials: 'same-origin', signal: options.signal });
    if (!response.ok) throw new Error(t('results.table.error.pageLoad'));
    const page = await response.json() as RawPage;
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

/** A cell as a finite number, or `null` for a blank/`NA` cell the format allows. */
export function cellNumber(value: string, columnName: string): number | null {
  const text = value.trim();
  if (text === '' || text.toLowerCase() === 'na' || text.toLowerCase() === 'nan') return null;
  const number = Number(text);
  if (!Number.isFinite(number)) throw new Error(t('results.table.error.notNumber', { column: columnName, value: text }));
  return number;
}
