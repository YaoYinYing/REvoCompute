import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { TaskSummary } from '../src/api/app-api';
import { applyLocale } from '../src/app/i18n';
import { Dashboard } from '../src/features/dashboard/index';
import { installHarness, type HarnessNode } from './dom-harness';

const task = (overrides: Partial<TaskSummary> = {}): TaskSummary => ({
  task_id: 'a'.repeat(32), task_type: 'sequence_demo', display_name: 'model.fasta',
  status: 'finished', terminal: true, submitted_at: '2026-09-20T10:00:00Z', finished_at: '2026-09-20T10:01:00Z',
  walltime_seconds: 60, owner: 'ada', placement: null, progress: null, outcome: 'SUCCESS', error: null,
  result: { available: true, publication: 'available', page_url: '/result', manifest_url: '/manifest', archive_ready: false, archive_request_allowed: true, archive_request_url: '/archive', download_url: null },
  actions: { cancel: { allowed: false, url: '/cancel' }, delete: { allowed: true, url: '/delete' } }, input_preview: null,
  ...overrides,
});

const page = (tasks: TaskSummary[], next: string | null = null) => ({
  tasks, next_cursor: next, has_more: Boolean(next), returned: tasks.length, cursor_reset: false,
  query: { q: null, task_type: null, status: null, owner: null, submitted_from: null, submitted_to: null, finished_from: null, finished_to: null, sort: 'submitted', limit: 30 },
});

beforeEach(() => { installHarness(vi.stubGlobal); });
afterEach(() => { applyLocale('en', false); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function build(): { dashboard: Dashboard; root: HarnessNode } {
  const root = document.createElement('div') as unknown as HarnessNode;
  const dashboard = new Dashboard(root as unknown as HTMLElement, { notify: vi.fn(), setUser: vi.fn() } as never, { role: 'user', username: 'tester' } as never);
  return { dashboard, root };
}

const requestedUrls = (fetchMock: ReturnType<typeof vi.fn>): string[] => fetchMock.mock.calls.map(call => String(call[0]));

describe('dashboard history pagination', () => {
  it('fetches one bounded page, then appends the next cursor without rebuilding', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes('cursor=next-page')) return new Response(JSON.stringify(page([task({ task_id: 'b'.repeat(32), display_name: 'older.fasta' })])), { status: 200, headers: { 'content-type': 'application/json' } });
      return new Response(JSON.stringify(page([task()], 'next-page')), { status: 200, headers: { 'content-type': 'application/json' } });
    });
    vi.stubGlobal('fetch', fetchMock);
    const { dashboard, root } = build();

    await dashboard.load();
    expect(root.querySelectorAll('.task-card')).toHaveLength(1);
    expect(root.querySelector('.list-count')?.textContent).toBe('1 tasks loaded; older history is available');
    const more = root.querySelector('[data-action="load-more"]') as HarnessNode;
    expect(more.hidden).toBe(false);
    expect(requestedUrls(fetchMock)[0]).toContain('limit=30');

    more.dispatch('click', {});
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(root.querySelectorAll('.task-card')).toHaveLength(2);
    expect(requestedUrls(fetchMock)[1]).toContain('cursor=next-page');
    expect(root.querySelector('[data-action="load-more"]')!.hidden).toBe(true);
    expect(root.querySelector('.list-state')?.textContent).toBe('End of task history.');
  });

  it('debounces rapid typing and aborts the superseded request', async () => {
    const timers: Array<{ callback: () => void; cleared: boolean }> = [];
    (window as unknown as { setTimeout: (fn: () => void) => number; clearTimeout: (id: number) => void }).setTimeout = (fn: () => void) => {
      timers.push({ callback: fn, cleared: false });
      return timers.length;
    };
    (window as unknown as { setTimeout: (fn: () => void) => number; clearTimeout: (id: number) => void }).clearTimeout = (id: number) => {
      if (timers[id - 1]) timers[id - 1]!.cleared = true;
    };
    const signals: AbortSignal[] = [];
    let first = true;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      signals.push(init!.signal as AbortSignal);
      if (first) { first = false; return new Promise<Response>(() => undefined); }
      return Promise.resolve(new Response(JSON.stringify(page([])), { status: 200, headers: { 'content-type': 'application/json' } }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const { dashboard, root } = build();
    const input = root.querySelector('[data-filter="search"]') as unknown as HarnessNode & { value: string };

    void dashboard.load();
    const controls = root.querySelector('.work-toolbar') as HarnessNode;
    input.value = 'a';
    controls.dispatch('input', { target: input, currentTarget: controls });
    input.value = 'alpha';
    controls.dispatch('input', { target: input, currentTarget: controls });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(timers).toHaveLength(2);
    expect(timers[0]!.cleared).toBe(true);

    timers[1]!.callback();
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(signals[0]!.aborted).toBe(true);
    expect(requestedUrls(fetchMock)[1]).toContain('q=alpha');
  });

  it('keeps the Load more control mounted and busy while a page is in flight', async () => {
    let release: (() => void) | null = null;
    const pending = new Promise<void>(resolve => { release = resolve; });
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes('cursor=next-page')) {
        await pending;
        return new Response(JSON.stringify(page([task({ task_id: 'b'.repeat(32), display_name: 'older.fasta' })])), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      return new Response(JSON.stringify(page([task()], 'next-page')), { status: 200, headers: { 'content-type': 'application/json' } });
    });
    vi.stubGlobal('fetch', fetchMock);
    const { dashboard, root } = build();

    await dashboard.load();
    const more = root.querySelector('[data-action="load-more"]') as HarnessNode;
    more.dispatch('click', {});
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(more.hidden).toBe(false);
    expect(more.getAttribute('aria-busy')).toBe('true');
    expect(more.getAttribute('aria-disabled')).toBe('true');

    release!();
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(root.querySelectorAll('.task-card')).toHaveLength(2);
    expect(more.hidden).toBe(true);
  });

  it('rebuilds page one when a continuation cursor resets', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes('cursor=next-page')) {
        return new Response(JSON.stringify({ ...page([task({ task_id: 'c'.repeat(32), display_name: 'fresh.fasta' })]), cursor_reset: true }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      return new Response(JSON.stringify(page([task()], 'next-page')), { status: 200, headers: { 'content-type': 'application/json' } });
    });
    vi.stubGlobal('fetch', fetchMock);
    const { dashboard, root } = build();

    await dashboard.load();
    (root.querySelector('[data-action="load-more"]') as HarnessNode).dispatch('click', {});
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(root.querySelectorAll('.task-card')).toHaveLength(1);
    expect(root.querySelector('.task-card .task-identity h2')?.textContent).toBe('fresh.fasta');
    expect(root.querySelector('.list-state')?.textContent).toBe('The previous page token no longer matched these filters; showing the first page again.');
  });

  it('removes the client-side regex control and explains literal search', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(page([])), { status: 200, headers: { 'content-type': 'application/json' } })));
    const { dashboard, root } = build();
    await dashboard.load();
    expect(root.querySelector('[data-toggle-regex]')).toBeNull();
    expect(root.querySelector('#dashboard-search-hint')?.textContent).toContain('literal');
  });
});
