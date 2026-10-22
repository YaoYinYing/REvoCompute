/*
 * Server-declared `scalar-summary` ResultView rendering: each field the task
 * declared, read from the first published source by its declared dotted path and
 * shown through the shared ScalarMetricGrid. Nothing is rescaled, recomputed, or
 * given meaning the declaration does not state.
 */
import type { ResultView } from '../../api/result-types';
import { t } from '../../app/i18n';
import { ScalarMetricGrid } from './scientific';
import type { ResolvedViewSources, ViewRenderer } from './renderer-registry';

/** The server rejects a scalar-summary source above 8 MiB before publishing it. */
const MAX_SUMMARY_BYTES = 8 * 1024 * 1024;
const DIRECTIONS = new Set(['higher', 'lower', 'neutral']);

interface ScalarField {
  path: string;
  label: string;
  unit: string;
  direction: string;
  nullable?: boolean;
}

export interface ScalarMetric {
  label: string;
  value: unknown;
  unit?: string;
  meaning?: string;
  nullable?: boolean;
}

/**
 * Read one declared scalar path: dotted object keys, with a decimal part indexing
 * an array. Mirrors the server's own `_json_path`, so a path the task declared is
 * resolved identically on both sides.
 */
export function resolveScalarPath(payload: unknown, path: string): unknown {
  let node: unknown = payload;
  for (const part of path.split('.')) {
    if (Array.isArray(node) && /^\d+$/.test(part)) node = node[Number(part)];
    else if (node !== null && typeof node === 'object' && !Array.isArray(node) && part in node) {
      node = (node as Record<string, unknown>)[part];
    } else return undefined;
  }
  return node;
}

function isScalar(value: unknown): value is string | number | boolean {
  return typeof value === 'string' || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value));
}

/** Validate the declaration the server projected; an invalid one is a contract fault, not data. */
export function declaredFields(view: ResultView): ScalarField[] {
  const fields = (view.mapping as { fields?: unknown } | undefined)?.fields;
  if (!Array.isArray(fields) || !fields.length) throw new Error(t('results.scalar.error.declaration'));
  return fields.map((field) => {
    if (
      !field || typeof field !== 'object' || typeof field.path !== 'string' || !field.path ||
      typeof field.label !== 'string' || !field.label || typeof field.unit !== 'string' ||
      !DIRECTIONS.has(field.direction) || ('nullable' in field && typeof field.nullable !== 'boolean')
    ) throw new Error(t('results.scalar.error.declaration'));
    return field as ScalarField;
  });
}

/**
 * Resolve the declared fields against one published summary object.
 *
 * A declared non-nullable path that is absent or not a scalar is a defect in the
 * published data, so it fails the view rather than rendering a plausible-looking
 * gap; a declared nullable null renders as N/A through the primitive.
 */
export function scalarMetrics(payload: unknown, fields: ScalarField[]): ScalarMetric[] {
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error(t('results.scalar.error.malformed'));
  }
  return fields.map((field) => {
    const value = resolveScalarPath(payload, field.path);
    if (value == null) {
      if (field.nullable) return { label: field.label, value: null, unit: field.unit, meaning: directionWording(field.direction), nullable: true };
      throw new Error(t('results.scalar.error.field', { path: field.path }));
    }
    if (!isScalar(value)) throw new Error(t('results.scalar.error.field', { path: field.path }));
    return { label: field.label, value, unit: field.unit, meaning: directionWording(field.direction) };
  });
}

function directionWording(direction: string): string {
  if (direction === 'higher') return t('results.scalar.higher');
  if (direction === 'lower') return t('results.scalar.lower');
  return '';
}

/** Render a declared `scalar-summary` view through the shared ScalarMetricGrid. */
export function createScalarSummaryViewRenderer(): ViewRenderer {
  return {
    id: 'scalar-summary',
    async render(view: ResultView, sources: ResolvedViewSources, host: HTMLElement, context) {
      const fields = declaredFields(view);
      const artifacts = sources.data || [];
      const source = artifacts[0];
      if (!source || !('url' in source)) throw new Error(t('results.scalar.error.noSource'));
      if (source.size > MAX_SUMMARY_BYTES) throw new Error(t('results.scalar.error.tooLarge'));
      const response = await fetch(source.url, { credentials: 'same-origin', signal: context.signal });
      if (!response.ok) throw new Error(t('results.scalar.error.load'));
      const metrics = scalarMetrics(await response.json(), fields);
      const section = document.createElement('section');
      section.className = 'scalar-summary-view';
      const gridHost = document.createElement('div');
      const grid = new ScalarMetricGrid(gridHost, metrics);
      const note = document.createElement('p');
      note.className = 'result-note';
      note.textContent = t('results.scalar.note');
      section.append(gridHost, note);
      if (artifacts.length > 1) {
        const more = document.createElement('p');
        more.className = 'result-note';
        more.textContent = t('results.scalar.firstOfMany', { count: artifacts.length });
        section.append(more);
      }
      host.replaceChildren(section);
      return { destroy: () => grid.destroy() };
    },
  };
}
