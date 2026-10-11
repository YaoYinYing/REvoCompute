import { readFile } from 'node:fs/promises';

import postcss from 'postcss';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { TaskSummary } from '../src/api/app-api';
import { Dashboard } from '../src/features/dashboard/index';
import { documentOrder, installHarness, type HarnessNode } from './dom-harness';

/*
 * The Dashboard register presents one Task two ways — a card and a Table row — and
 * §14.4 makes view mode a presentation choice over one contract, not a second data
 * model. These tests drive the real component and read the two views the way a
 * person does: the Table's Status cell must show the Task's state exactly as the
 * card's pill shows it, character for character.
 *
 * A rendered status is a source value plus the casing CSS paints on it, so
 * comparing `textContent` alone cannot see the difference: the card's pill takes
 * `capitalize` from the shared pill rule while a bare table cell takes none, and
 * the two views would still show different words. These tests therefore apply the
 * shipped `text-transform` rules to each view, so they fail whenever the rendered
 * casing of one view stops matching the other.
 */

const task = (overrides: Partial<TaskSummary> = {}): TaskSummary => ({
  task_id: 'a'.repeat(32), task_type: 'sequence_demo', display_name: 'model.fasta',
  status: 'finished', terminal: true, submitted_at: '2026-09-20T10:00:00Z', finished_at: '2026-09-20T10:01:00Z',
  walltime_seconds: 60, owner: 'ada', placement: null, progress: null, outcome: 'SUCCESS', error: null,
  result: { available: true, publication: 'available', page_url: '/result', manifest_url: '/manifest', archive_ready: false, archive_request_allowed: true, archive_request_url: '/archive', download_url: null },
  actions: { cancel: { allowed: false, url: '/cancel' }, delete: { allowed: true, url: '/delete' } }, input_preview: null,
  ...overrides,
});

beforeEach(() => {
  installHarness(vi.stubGlobal);
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ tasks: [] }), { status: 200, headers: { 'content-type': 'application/json' } })));
});

afterEach(() => vi.unstubAllGlobals());

/** Build a Dashboard whose card or Table view renders `tasks`, and return its root. */
function render(tasks: TaskSummary[], layout: 'detailed' | 'table', role: 'user' | 'admin' = 'user'): HarnessNode {
  const root = document.createElement('div') as unknown as HarnessNode;
  const dashboard = new Dashboard(root as unknown as HTMLElement, { notify: vi.fn(), setUser: vi.fn() } as never, { role, username: 'tester' } as never);
  const view = dashboard as unknown as { tasks: TaskSummary[]; query: Record<string, unknown>; render(): void };
  view.tasks = tasks;
  view.query = { ...view.query, layout };
  view.render();
  return root;
}

/** The index of a named column, so the assertion reads the column a person looks at. */
function columnIndex(root: HarnessNode, heading: string): number {
  const headers = root.querySelector('table.task-table thead tr')!.querySelectorAll('th');
  const index = headers.findIndex(header => header.textContent.trim() === heading);
  expect(index, `no column named ${heading}`).toBeGreaterThanOrEqual(0);
  return index;
}

/** The Table's Status cell for the first row, or the card's pill. */
function rowCell(root: HarnessNode, heading: string): HarnessNode {
  return root.querySelector('table.task-table tbody tr')!.querySelectorAll('td')[columnIndex(root, heading)]!;
}
function statusPill(root: HarnessNode): HarnessNode {
  return root.querySelector('article.task-card')!.querySelector('span.status')!;
}

/** The status the card shows, as a person reads it: source value plus its casing. */
function cardVisible(root: HarnessNode): string { return visible(statusPill(root)); }

/** The status the Table shows, as a person reads it: source value plus its casing. */
function tableVisible(root: HarnessNode): string { return visible(rowCell(root, 'Status')); }

/*
 * The dashboard stylesheet is parsed, not pattern-matched, so the test applies the
 * declared casing instead of asserting on CSS text. Every rule that declares a
 * `text-transform` is kept with its selector classes, in source order.
 */
const stylesheet = await readFile(new URL('../src/styles/app.css', import.meta.url), 'utf8');
const declaredRules = await readDeclaredTransformRules(stylesheet);

async function readDeclaredTransformRules(css: string): Promise<Array<{ classes: string[]; transform: string }>> {
  const rules: Array<{ classes: string[]; transform: string }> = [];
  const parsed = (await postcss.parse(css)).toJSON() as { nodes: Array<{ selector?: string; nodes?: Array<{ prop?: string; value?: string }> }> };
  for (const node of Object.values(parsed.nodes)) {
    const transform = (node.nodes ?? []).find(declaration => declaration.prop === 'text-transform')?.value;
    if (!transform || !node.selector) continue;
    // A selector list is satisfied by any one group, so each group is its own rule.
    for (const group of node.selector.split(',')) {
      const classes = [...group.matchAll(/\.([\w-]+)/g)].map(match => match[1]!);
      if (classes.length) rules.push({ classes, transform });
    }
  }
  return rules;
}

/**
 * The characters a person reads for a view: its source text, plus the casing the
 * stylesheet applies to it.
 *
 * The rule is chosen by class match, as a descendant selector reaches a view
 * through its stylesheet-matched ancestors; the later declaration of a matching
 * pair wins. A view that no shipped rule governs fails the test rather than
 * passing on an unstated assumption about its rendering.
 */
function visible(view: HarnessNode): string {
  const classes = new Set<string>();
  for (let current: HarnessNode | null = view; current; current = current.parentNode) {
    for (const name of current.className.split(/\s+/).filter(Boolean)) classes.add(name);
  }
  const matching = declaredRules.filter(rule => rule.classes.every(name => classes.has(name)));
  if (!matching.length) throw new Error(`no text-transform governs .${view.className}`);
  return applyTransform(view.textContent, matching[matching.length - 1]!.transform);
}

/** The layout-independent casing one `text-transform` value applies. */
function applyTransform(value: string, transform: string): string {
  if (transform === 'capitalize') return value.replace(/\b\p{L}/gu, letter => letter.toUpperCase());
  if (transform === 'uppercase') return value.toUpperCase();
  if (transform === 'lowercase') return value.toLowerCase();
  return value;
}

describe('Dashboard status vocabulary', () => {
  it('names a finished Task the same way in the card and in the Table Status cell', () => {
    const tasks = [task({ outcome: 'SUCCESS' })];
    expect(rowCell(render(tasks, 'table'), 'Status').textContent).toBe('SUCCESS');
    expect(statusPill(render(tasks, 'detailed')).textContent).toBe('SUCCESS');
  });

  it('renders one visible word for every Task state, not merely one source text', () => {
    // Every way the register can name a Task's state: a reported outcome, no
    // outcome at all (the ordinary finalized Task), an outcome the server
    // projected as empty, an outcome whose case must survive, a lifecycle enum
    // whose claim is spelled with a colon, and the non-terminal states a person
    // watches while the Task is still moving.
    const cases: Array<[string, TaskSummary]> = [
      ['reported outcome', task({ outcome: 'SUCCESS' })],
      ['outcome absent', task({ outcome: null })],
      ['outcome empty', task({ outcome: '' })],
      ['outcome case preserved', task({ outcome: 'PARTIAL_SUCCESS' })],
      ['running', task({ status: 'running', outcome: null, terminal: false, finished_at: null, result: { ...task().result, available: false } })],
      ['queued', task({ status: 'queued', outcome: null, terminal: false, finished_at: null, result: { ...task().result, available: false } })],
      ['failed without outcome', task({ status: 'failed', outcome: '' })],
      ['cancelled', task({ status: 'cancelled', outcome: null })],
      ['colon claim', task({ status: 'cleaned:finished', outcome: '' })],
    ];
    for (const [state, summary] of cases) {
      const card = cardVisible(render([summary], 'detailed'));
      const table = tableVisible(render([summary], 'table'));
      expect(table, `Table names ${state}`).toBe(card);
      // A raw machine enum and the same word in a table cell still differ on
      // screen, so the capitalization the card paints on the word must be there.
      expect(card, `card capitalizes ${state}`).toBe(card.charAt(0).toUpperCase() + card.slice(1));
    }
  });

  it('falls back to the lifecycle enum identically in both views when no outcome was reported', () => {
    const tasks = [task({ status: 'finished', outcome: null })];
    expect(rowCell(render(tasks, 'table'), 'Status').textContent).toBe('finished');
    expect(tableVisible(render(tasks, 'table'))).toBe('Finished');
    expect(statusPill(render(tasks, 'detailed')).textContent).toBe('finished');
  });

  it('keeps the raw enum on the row for filtering and sorting to read', () => {
    const root = render([task({ status: 'finished', outcome: 'SUCCESS' })], 'table');
    const row = root.querySelector('table.task-table tbody tr')!;
    const cell = rowCell(root, 'Status');
    // The Status cell is prose; it is not machine-text and carries no status-* class.
    expect(row.querySelector('td.machine')).toBeNull();
    expect(documentOrder(row).filter(node => node.className.startsWith('status'))).toEqual([]);
    // The cell reads the register's own vocabulary; it publishes no second
    // machine-identity attribute for the row.
    expect(cell.textContent).toBe('SUCCESS');
  });
});
