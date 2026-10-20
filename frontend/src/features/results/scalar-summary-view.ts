/*
 * `scalar-summary` ResultView rendering: the Task's declared fields read from one JSON
 * document and presented through the shared ScalarMetricGrid primitive.
 *
 * Only the paths, labels, units, and directions the Task declared are shown. A field the
 * document does not carry is omitted unless the mapping declares it nullable.
 */
import type { ResultFile, ResultView } from '../../api/result-types';
import { ScalarMetricGrid } from './scientific';
import type { ResolvedViewSources, ViewRenderer } from './renderer-registry';

export interface ScalarField {
  path: string;
  label?: string;
  unit?: string;
  direction?: string;
  nullable?: boolean;
}

function valueAt(document: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((value, key) => (
    value && typeof value === 'object' ? (value as Record<string, unknown>)[key] : undefined
  ), document);
}

/** The declared fields as grid entries; a missing non-nullable value is dropped. */
export function summaryMetrics(document: unknown, fields: ScalarField[]): Array<{ label: string; value: unknown; unit?: string; meaning?: string; nullable?: boolean }> {
  return fields.map((field) => ({
    label: field.label || field.path,
    value: valueAt(document, field.path),
    unit: field.unit,
    meaning: field.direction === 'higher' ? 'higher is stronger' : field.direction === 'lower' ? 'lower is stronger' : undefined,
    nullable: field.nullable,
  }));
}

async function fetchJson(source: ResultFile | undefined, signal: AbortSignal): Promise<unknown> {
  if (!source) throw new TypeError('The scalar summary view has no declared data source.');
  if (Number(source.size) > 1_048_576) throw new Error('The scalar summary document exceeds the preview limit.');
  const response = await fetch(source.url, { credentials: 'same-origin', signal });
  if (!response.ok) throw new Error('The scalar summary document could not be loaded.');
  return response.json();
}

/** Render a declared `scalar-summary` view through the shared ScalarMetricGrid primitive. */
export function createScalarSummaryViewRenderer(): ViewRenderer {
  return {
    id: 'scalar-summary',
    async render(view: ResultView, sources: ResolvedViewSources, host: HTMLElement, context) {
      const fields = ((view.mapping || {}).fields || []) as ScalarField[];
      if (!fields.length) throw new TypeError('The scalar summary view declares no fields.');
      const document = await fetchJson(sources.data?.[0], context.signal);
      const grid = new ScalarMetricGrid(host, summaryMetrics(document, fields));
      return { destroy: () => grid.destroy() };
    },
  };
}
