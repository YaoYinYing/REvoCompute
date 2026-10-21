/*
 * Server-declared `entity-table` ResultView rendering: bounded table paging plus the shared
 * EntitySummaryTable primitive.
 *
 * The Task declares which columns identify an entity and which are its evidence; this renderer
 * reads exactly those columns through the manifest mapping. It never infers an entity, a score
 * direction, or a unit from a filename or a column value.
 */
import type { ResultView } from '../../api/result-types';
import { t } from '../../app/i18n';
import { EntitySummaryTable } from './scientific';
import type { ResolvedViewSources, ViewRenderer } from './renderer-registry';
import { loadTable, tableUrlOf } from './table-page';

/** Declared view mapping keys, in the server's own snake_case vocabulary. */
export interface EntityTableMapping {
  entity?: string;
  key_columns?: string[];
  label_column?: string;
  evidence_columns?: string[];
  chain_column?: string;
  residue_column?: string;
  numbering?: string;
}

/** The columns a table view presents: the entity's identity, then its declared evidence. */
export function entityColumns(mapping: EntityTableMapping, available: string[]): string[] {
  const wanted = [mapping.label_column, ...(mapping.key_columns || []), ...(mapping.evidence_columns || [])]
    .filter((name): name is string => typeof name === 'string' && name !== '');
  const unique = [...new Set(wanted)].filter((name) => available.includes(name));
  if (!unique.length) throw new Error(t('results.entityTable.error.noColumns'));
  return unique;
}

/** Render a declared `entity-table` view through the shared EntitySummaryTable primitive. */
export function createEntityTableViewRenderer(): ViewRenderer {
  return {
    id: 'entity-table',
    async render(view: ResultView, sources: ResolvedViewSources, host: HTMLElement, context) {
      const mapping = (view.mapping || {}) as EntityTableMapping;
      const url = tableUrlOf(sources.table?.[0], context.taskId);
      const { page, truncated } = await loadTable(url, { signal: context.signal });
      const columns = entityColumns(mapping, page.columns);
      const indices = columns.map((name) => page.columns.indexOf(name));
      const rows = page.rows.map((row) => indices.map((index) => row[index]));
      const section = document.createElement('section'); section.className = 'entity-table-view';
      const tableHost = document.createElement('div');
      section.append(tableHost); host.replaceChildren(section);
      const table = new EntitySummaryTable(tableHost, { columns, rows });
      if (truncated) {
        const note = document.createElement('p'); note.className = 'result-note';
        note.textContent = t('results.table.truncated'); section.append(note);
      }
      return { destroy: () => table.destroy() };
    },
  };
}
