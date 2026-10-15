import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { TaskDiagnostics } from '../src/api/app-api';
import { mountTaskDiagnostics } from '../src/features/tasks/diagnostics';
import { installHarness, type HarnessNode } from './dom-harness';

const getDiagnostics = vi.hoisted(() => vi.fn());
vi.mock('../src/api/app-api', () => ({ getTaskDiagnostics: getDiagnostics }));
const evidence = (overrides: Partial<TaskDiagnostics> = {}): TaskDiagnostics => ({
  task_id: 'a'.repeat(32), availability: 'available', summary: 'Execution failed.', reason_code: 'nonzero_exit',
  exit_code: 2, exit_code_source: 'srun', scheduler_state: null, stage: 'fit', logs: [], ...overrides,
});
let host: HarnessNode;
beforeEach(() => { installHarness(vi.stubGlobal); host = document.createElement('section') as unknown as HarnessNode; getDiagnostics.mockReset(); });
afterEach(() => vi.unstubAllGlobals());

it('shows confirmed zero separately from an unknown exit and renders context as text', async () => {
  getDiagnostics.mockResolvedValue(evidence({ exit_code: 0, reason_code: 'publication_failed', logs: [{
    stream: 'stderr', preview: '<img src=x onerror=alert(1)>', truncated: true, download_url: '/safe/excerpt',
  }] }));
  mountTaskDiagnostics(host as unknown as HTMLElement, 'a'.repeat(32), new AbortController().signal);
  await vi.waitFor(() => expect(host.textContent).toContain('0 (srun)'));
  expect(host.querySelector('img')).toBeNull();
  expect(host.querySelector('pre')?.textContent).toContain('<img');
  expect(host.querySelector('a')?.href).toBe('/safe/excerpt');
  expect(host.textContent).toContain('excerpt');
});

it('states missing evidence explicitly without inventing an exit or log link', async () => {
  getDiagnostics.mockResolvedValue(evidence({ availability: 'expired', exit_code: null, exit_code_source: null, reason_code: null }));
  mountTaskDiagnostics(host as unknown as HTMLElement, 'a'.repeat(32), new AbortController().signal);
  await vi.waitFor(() => expect(host.getAttribute('aria-busy')).toBe('false'));
  expect(host.textContent).toContain('Not available');
  expect(host.textContent).toContain('no longer retained');
  expect(host.querySelector('a')).toBeNull();
});

it('offers a bounded explicit retry and ignores a request disposed while pending', async () => {
  getDiagnostics.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(evidence());
  const controller = new AbortController();
  mountTaskDiagnostics(host as unknown as HTMLElement, 'a'.repeat(32), controller.signal);
  await vi.waitFor(() => expect(host.querySelector('button')).not.toBeNull());
  host.querySelector('button')!.dispatch('click', {});
  await vi.waitFor(() => expect(host.textContent).toContain('2 (srun)'));
  expect(getDiagnostics).toHaveBeenCalledTimes(2);
  let resolve!: (value: TaskDiagnostics) => void;
  getDiagnostics.mockImplementationOnce(() => new Promise<TaskDiagnostics>(done => { resolve = done; }));
  mountTaskDiagnostics(host as unknown as HTMLElement, 'a'.repeat(32), controller.signal);
  controller.abort(); resolve(evidence({ summary: 'late response' }));
  await Promise.resolve();
  expect(host.textContent).not.toContain('late response');
});
