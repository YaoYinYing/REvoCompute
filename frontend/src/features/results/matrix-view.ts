/*
 * Server-declared `matrix` ResultView rendering: bounded CSV paging plus the shared
 * PairMatrix primitive. The loader reads only the manifest mapping vocabulary the task
 * declared; it never infers scientific meaning from a filename.
 */
import type { ResultFile, ResultView } from '../../api/result-types';
import { MAX_ELEMENTS, PairMatrix } from './scientific';
import type { ViewRenderer } from './renderer-registry';

/** The server rejects `limit` above 500 and `offset` above 10000. */
const PAGE_LIMIT = 500;
const MAX_OFFSET = 10_000;
/** Only `matrix=1` raises the server's column cap from 100 to 512. */
const MAX_COLUMNS = 512;

/** Declared view mapping keys, in the server's own snake_case vocabulary. */
export interface MatrixMapping {
  row_labels_column?: string;
  x_label?: string;
  y_label?: string;
  unit?: string;
  direction?: string;
  scale?: string;
  scale_min?: number;
  scale_max?: number;
  center?: number;
}

export interface MatrixSeries {
  values: Array<Array<number | null>>;
  xLabels: string[];
  yLabels: string[];
}

interface TablePage {
  columns: unknown[];
  rows: unknown[][];
  has_more?: boolean;
}

function numberOrNull(cell: unknown): number | null {
  const text = String(cell ?? '').trim();
  if (text === '') return null;
  const value = Number(text);
  if (!Number.isFinite(value)) throw new Error('The matrix contains a value that is not a number.');
  return value;
}

/**
 * Page one bounded matrix table into dense values plus axis labels.
 *
 * Rows are read with `limit` ≤ 500 until `has_more` is false, and the assembled
 * element count is checked against the shared browser budget on every page, so an
 * unbounded matrix fails with a clear error instead of exhausting memory.
 */
export async function loadMatrixSeries(
  tableUrl: string | undefined,
  mapping: MatrixMapping,
  options: { signal?: AbortSignal; maxElements?: number } = {},
): Promise<MatrixSeries> {
  if (!tableUrl) throw new TypeError('The matrix view has no bounded table URL.');
  const maximum = options.maxElements ?? MAX_ELEMENTS;
  if (!Number.isInteger(maximum) || maximum < 1 || maximum > MAX_ELEMENTS) {
    throw new RangeError('Matrix element limits are invalid.');
  }
  const base = tableUrl.includes('?') ? `${tableUrl}&` : `${tableUrl}?`;
  let columns: string[] | null = null;
  const rows: unknown[][] = [];
  let offset = 0;
  let valueColumns = 0;
  for (;;) {
    const query = new URLSearchParams({ matrix: '1', offset: String(offset), limit: String(PAGE_LIMIT) });
    const response = await fetch(`${base}${query}`, { credentials: 'same-origin', signal: options.signal });
    if (!response.ok) throw new Error('The matrix page could not be loaded.');
    const page = await response.json() as TablePage;
    const header = Array.isArray(page.columns) ? page.columns.map(String) : null;
    if (!header || header.length < 2 || header.length > MAX_COLUMNS || !Array.isArray(page.rows)) {
      throw new Error('The matrix page is malformed.');
    }
    if (columns === null) columns = header;
    if (page.rows.some((row) => !Array.isArray(row) || row.length !== columns!.length)) {
      throw new Error('The matrix page is malformed.');
    }
    valueColumns = columns.length - (mapping.row_labels_column ? 1 : 0);
    if ((rows.length + page.rows.length) * valueColumns > maximum) {
      throw new RangeError('The matrix exceeds the browser element limit.');
    }
    rows.push(...page.rows);
    if (!page.has_more) break;
    if (page.rows.length === 0) throw new Error('The matrix page is malformed.');
    offset += page.rows.length;
    if (offset > MAX_OFFSET) throw new Error('The matrix exceeds the bounded server page window.');
  }
  if (columns === null || !rows.length) throw new Error('The matrix is empty.');

  const declared = mapping.row_labels_column;
  const labelIndex = declared ? columns.indexOf(declared) : -1;
  if (declared && labelIndex !== 0) throw new Error(`The matrix is missing its declared row label column ${declared}.`);
  const xLabels = labelIndex === 0 ? columns.slice(1) : [...columns];
  const yLabels: string[] = [];
  const values = rows.map((row) => {
    if (labelIndex === 0) yLabels.push(String(row[0] ?? ''));
    return (labelIndex === 0 ? row.slice(1) : row).map(numberOrNull);
  });
  return { values, xLabels, yLabels };
}

export interface MatrixRange { minimum: number; maximum: number; }

/**
 * Resolve the colour range the primitive draws with.
 *
 * A `diverging` scale with `center: 0` becomes the symmetric range
 * `min = -m, max = +m` with `m = max(|observed min|, |observed max|)`, so zero
 * lands exactly on the ramp's neutral midpoint and negatives render as negative.
 * A task-declared `scale_min`/`scale_max` always wins over the observed extent.
 */
export function matrixRange(values: Array<Array<number | null>>, mapping: MatrixMapping): MatrixRange | null {
  let observedMinimum = Number.POSITIVE_INFINITY;
  let observedMaximum = Number.NEGATIVE_INFINITY;
  for (const row of values) {
    for (const value of row) {
      if (value == null || !Number.isFinite(value)) continue;
      if (value < observedMinimum) observedMinimum = value;
      if (value > observedMaximum) observedMaximum = value;
    }
  }
  if (observedMinimum === Number.POSITIVE_INFINITY) return null;
  const declaredMinimum = typeof mapping.scale_min === 'number' ? mapping.scale_min : null;
  const declaredMaximum = typeof mapping.scale_max === 'number' ? mapping.scale_max : null;
  if (mapping.scale === 'diverging') {
    const center = typeof mapping.center === 'number' ? mapping.center : 0;
    const half = Math.max(Math.abs(observedMinimum - center), Math.abs(observedMaximum - center)) || 1;
    return { minimum: declaredMinimum ?? center - half, maximum: declaredMaximum ?? center + half };
  }
  const fallbackMaximum = observedMaximum === observedMinimum ? observedMinimum + 1 : observedMaximum;
  return { minimum: declaredMinimum ?? observedMinimum, maximum: declaredMaximum ?? fallbackMaximum };
}

type Theme = 'light' | 'dark';

/** Diverging ramps run negative → neutral → positive, with a theme-selected neutral. */
const DIVERGING_RAMPS: Record<Theme, string[]> = {
  light: ['#2166ac', '#92c5de', '#f0efec', '#f4a582', '#b2182b'],
  dark: ['#4fa3d1', '#2c5a72', '#26343a', '#6b4340', '#e08a76'],
};
const SEQUENTIAL_RAMPS: Record<Theme, string[]> = {
  light: ['#eef7fb', '#7db9dc', '#155b8a'],
  dark: ['#1d2b33', '#3d7d99', '#9ed6ea'],
};

function currentTheme(): Theme {
  return typeof document !== 'undefined' && document.documentElement?.dataset?.theme === 'dark' ? 'dark' : 'light';
}

/** Resolve the ramp at draw time so a theme toggle repaints without a remount. */
export function matrixRamp(scale: string | undefined, theme: Theme = currentTheme()): string[] {
  const ramps = scale === 'diverging' ? DIVERGING_RAMPS : SEQUENTIAL_RAMPS;
  return [...ramps[theme]];
}

function legendTitle(mapping: MatrixMapping): string {
  const scale = mapping.scale === 'diverging' ? ' (negative → positive)' : ' (low → high)';
  return `${mapping.unit || 'Value'}${scale}`;
}

function directionWording(direction: string | undefined): string {
  if (direction === 'higher') return 'higher is stronger';
  if (direction === 'lower') return 'lower is stronger';
  return '';
}

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

/** Render a declared `matrix` view through the shared bounded PairMatrix primitive. */
export function createMatrixViewRenderer(): ViewRenderer {
  return {
    id: 'matrix',
    async render(view: ResultView, source: ResultFile | null, host: HTMLElement, context) {
      const mapping = (view.mapping || {}) as MatrixMapping;
      const tableUrl = source && 'table_url' in source ? source.table_url : undefined;
      const series = await loadMatrixSeries(tableUrl, mapping, { signal: context.signal });
      const range = matrixRange(series.values, mapping);
      const xTitle = mapping.x_label || 'Position';
      const yTitle = mapping.y_label || 'Position';
      const split = element('section', 'pair-matrix-view');
      const figure = element('figure', 'pair-matrix-figure');
      const canvas = element('canvas');
      canvas.tabIndex = 0;
      canvas.setAttribute('role', 'img');
      canvas.setAttribute('aria-label', `${view.title} matrix`);
      const readout = element('p', 'pair-matrix-readout');
      readout.setAttribute('role', 'status');
      readout.setAttribute('aria-live', 'polite');
      figure.append(canvas);
      split.append(figure, readout);
      host.replaceChildren(split);
      const direction = directionWording(mapping.direction);
      const matrix = new PairMatrix({
        figure, canvas, readout, observe: split, maxElements: MAX_ELEMENTS,
        minimum: range?.minimum, maximum: range?.maximum,
        ramp: () => matrixRamp(mapping.scale),
        // An even tick count keeps a labelled tick on a symmetric diverging midpoint.
        ticks: mapping.scale === 'diverging' ? 4 : undefined,
        xTitle, yTitle, unit: mapping.unit, legendTitle: legendTitle(mapping), decimals: 2,
        formatReadout: (cell: Record<string, any>) => {
          const value = Number.isFinite(cell.value) ? cell.value.toFixed(2) : 'N/A';
          const suffix = `${value}${mapping.unit ? ` ${mapping.unit}` : ''}`;
          return `${xTitle} ${cell.xLabel} · ${yTitle} ${cell.yLabel} · ${suffix}${direction ? ` (${direction})` : ''}`;
        },
      });
      matrix.setData({ values: series.values, xLabels: series.xLabels, yLabels: series.yLabels });
      return { destroy: () => matrix.destroy() };
    },
  };
}
