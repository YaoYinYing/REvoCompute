import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { TaskSummary } from '../src/api/app-api';
import { Dashboard } from '../src/features/dashboard/index';
import { documentOrder, installHarness, type HarnessNode } from './dom-harness';

/*
 * The Dashboard register presents one Task two ways — a card and a Table row — and
 * §14.4 makes view mode a presentation choice over one contract, not a second data
 * model. These tests drive the real component and read the two views the way a
 * person does: the Table's Status cell must publish the Task's own state exactly
 * as the card's pill publishes it, character for character.
 *
 * This is the DOM contract: the two views agree on the source vocabulary they
 * render. The casing a browser paints on that vocabulary is resolved by CSS, which
 * a unit test cannot compute, so it is owned by the browser acceptance
 * `tests/test_playwright_runner_fixtures.py::test_dashboard_table_status_cell_reads_like_the_card_pill`.
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
function render(tasks: TaskSummary[], layout: 'detailed' | 'compact' | 'table', role: 'user' | 'admin' = 'user'): HarnessNode {
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

describe('Dashboard status vocabulary', () => {
  it('names a finished Task the same way in the card and in the Table Status cell', () => {
    const tasks = [task({ outcome: 'SUCCESS' })];
    expect(rowCell(render(tasks, 'table'), 'Status').textContent).toBe('SUCCESS');
    expect(statusPill(render(tasks, 'detailed')).textContent).toBe('SUCCESS');
  });

  it('publishes one word for every Task state in both views, not merely one source text', () => {
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
      const card = statusPill(render([summary], 'detailed')).textContent;
      const table = rowCell(render([summary], 'table'), 'Status').textContent;
      expect(table, `Table names ${state}`).toBe(card);
    }
  });

  it('falls back to the lifecycle enum identically in both views when no outcome was reported', () => {
    const tasks = [task({ status: 'finished', outcome: null })];
    expect(rowCell(render(tasks, 'table'), 'Status').textContent).toBe('finished');
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


it('gives a failed Task a direct View error action in both Dashboard layouts', () => {
  for (const layout of ['detailed', 'compact', 'table'] as const) {
    const summary = task({ status: 'failed', outcome: null });
    summary.result = { ...summary.result, available: false };
    const root = render([summary], layout);
    const action = root.querySelector('button[data-action="diagnostics"]');
    expect(action?.textContent).toContain('View error');
    expect(root.querySelector('a[href="/result"]')?.textContent).toContain('View details');
    expect(root.querySelector('button[data-action="delete"]')).not.toBeNull();
  }
});
