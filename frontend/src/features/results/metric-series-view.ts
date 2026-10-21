/*
 * Server-declared `metric-series` ResultView rendering: bounded table paging plus the shared
 * LocalConfidenceSeries primitive.
 *
 * The Task declares the x column, the value columns, and the axis wording. The renderer plots
 * exactly those columns; it never labels an axis with a physical quantity, a unit, or a
 * "confidence" the mapping did not declare.
 */
import type { ResultView } from '../../api/result-types';
import { LocalConfidenceSeries } from './scientific';
import type { ResolvedViewSources, ViewRenderer } from './renderer-registry';
import { column, loadTable, tableUrlOf } from './table-page';

export interface MetricSeriesMapping {
  format?: string;
  x_column?: string;
  value_columns?: string[];
  x_label?: string;
  y_label?: string;
  unit?: string;
  direction?: string;
  missing?: string;
  y_min?: number;
  y_max?: number;
}

/** One declared column as finite numbers; a blank or `NA` cell is a gap, not a zero. */
export function seriesValues(cells: string[]): Array<number | null> {
  return cells.map((cell) => {
    const text = cell.trim();
    if (text === '' || text.toLowerCase() === 'na') return null;
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
  });
}

/** A series' finite extent, and the declared bounds when the mapping names them. */
export function seriesRange(values: Array<number | null>, mapping: MetricSeriesMapping): { minimum: number; maximum: number } {
  const finite = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  return {
    minimum: typeof mapping.y_min === 'number' ? mapping.y_min : (finite.length ? Math.min(...finite) : 0),
    maximum: typeof mapping.y_max === 'number' ? mapping.y_max : (finite.length ? Math.max(...finite) : 1),
  };
}

/**
 * Render a declared `metric-series` view through the shared LocalConfidenceSeries primitive.
 *
 * Each declared `value_columns` entry becomes one series. The chart's own y-axis is drawn from
 * the union of the series, so the unit in the legend is the mapping's single declared unit --
 * a view whose columns carry different units must declare them per series instead.
 */
export function createMetricSeriesViewRenderer(): ViewRenderer {
  return {
    id: 'metric-series',
    async render(view: ResultView, sources: ResolvedViewSources, host: HTMLElement, context) {
      const mapping = (view.mapping || {}) as MetricSeriesMapping;
      const url = tableUrlOf(sources.series?.[0], context.taskId);
      const { page } = await loadTable(url, { signal: context.signal });
      const xColumn = mapping.x_column;
      if (!xColumn) throw new TypeError('The metric series view declares no x column.');
      const xValues = column(page, xColumn).map((cell) => Number(cell.trim()));
      if (xValues.some((value) => !Number.isFinite(value))) throw new Error('The metric series x column is not numeric.');
      const names = mapping.value_columns || [];
      if (!names.length) throw new TypeError('The metric series view declares no value columns.');
      const series = names.map((name) => ({ label: name, values: seriesValues(column(page, name)) }));
      const range = seriesRange(series.flatMap((item) => item.values), mapping);
      const section = document.createElement('section'); section.className = 'metric-series-view';
      const chartHost = document.createElement('div');
      const legend = document.createElement('ul'); legend.className = 'metric-series-legend';
      series.forEach((item) => {
        const row = document.createElement('li'); row.textContent = item.label;
        row.append(document.createTextNode(` · ${item.values.filter((value) => value != null).length} values`));
        legend.append(row);
      });
      const unit = document.createElement('p'); unit.className = 'result-note';
      unit.textContent = [mapping.y_label, mapping.unit].filter(Boolean).join(' · ');
      section.append(chartHost, legend, unit); host.replaceChildren(section);
      const chart = new LocalConfidenceSeries(chartHost, {
        series, xValues,
        xLabel: mapping.x_label, yLabel: mapping.y_label, unit: mapping.unit,
        yMin: range.minimum, yMax: range.maximum,
        onSelect: (point: { index: number; x: number; values: unknown[] }) => {
          host.dispatchEvent(new CustomEvent('result-series-select', { detail: point }));
        },
      });
      return { destroy: () => chart.destroy() };
    },
  };
}

