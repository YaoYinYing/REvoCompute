import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { TaskSummary } from '../src/api/app-api';
import { Dashboard } from '../src/features/dashboard/index';
import { documentOrder, installHarness, type HarnessNode } from './dom-harness';

/*
 * The Dashboard register presents one Task two ways — a card and a Table row — and
 * §14.4 makes view mode a presentation choice over one contract, not a second data
 * model. These tests drive the real component and read the two views the way a
 * person does: the Table's Status cell must name the Task's state exactly as the
 * card does. Both views read the same task, so a difference is a defect, not a
 * styling choice.
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

/** The status the card shows: the pill in the card header, as a person reads it. */
function cardStatus(root: HarnessNode): string {
  const card = root.querySelector('article.task-card')!;
  return card.querySelector('span.status')!.textContent;
}

/** The index of a named column, so the assertion reads the column a person looks at. */
function columnIndex(root: HarnessNode, heading: string): number {
  const headers = root.querySelector('table.task-table thead tr')!.querySelectorAll('th');
  const index = headers.findIndex(header => header.textContent.trim() === heading);
  expect(index, `no column named ${heading}`).toBeGreaterThanOrEqual(0);
  return index;
}

/** The status the Table shows: the Status column of the first row. */
function tableStatus(root: HarnessNode): string {
  const row = root.querySelector('table.task-table tbody tr')!;
  return row.querySelectorAll('td')[columnIndex(root, 'Status')]!.textContent;
}

describe('Dashboard status vocabulary', () => {
  it('names a finished Task the same way in the card and in the Table Status cell', () => {
    const tasks = [task({ outcome: 'SUCCESS' })];
    expect(tableStatus(render(tasks, 'table'))).toBe('SUCCESS');
    expect(cardStatus(render(tasks, 'detailed'))).toBe('SUCCESS');
  });

  it('falls back to the lifecycle enum identically in both views when no outcome was reported', () => {
    const tasks = [task({ status: 'finished', outcome: null })];
    expect(tableStatus(render(tasks, 'table'))).toBe('finished');
    expect(cardStatus(render(tasks, 'detailed'))).toBe('finished');
  });

  it('keeps one vocabulary for a non-terminal Task in both views', () => {
    const tasks = [task({ status: 'running', outcome: null, terminal: false, finished_at: null, result: { ...task().result, available: false } })];
    const table = render(tasks, 'table');
    const cards = render(tasks, 'detailed');
    expect(tableStatus(table)).toBe('running');
    expect(cardStatus(cards)).toBe('running');
  });

  it('keeps the raw enum on the row for filtering and sorting to read', () => {
    const root = render([task({ status: 'finished', outcome: 'SUCCESS' })], 'table');
    const row = root.querySelector('table.task-table tbody tr')!;
    // The Status cell is prose; it is not machine-text and carries no status-* class.
    expect(row.querySelector('td.machine')).toBeNull();
    expect(documentOrder(row).filter(node => node.className.startsWith('status'))).toEqual([]);
  });
});
