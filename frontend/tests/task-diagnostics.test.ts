import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { TaskDiagnostics } from '../src/api/app-api';
import { mountTaskDiagnostics } from '../src/features/tasks/diagnostics';
import { installHarness, type HarnessNode } from './dom-harness';

const getDiagnostics = vi.hoisted(() => vi.fn());
const getExcerpt = vi.hoisted(() => vi.fn());
vi.mock('../src/api/app-api', () => ({ getTaskDiagnostics: getDiagnostics, getTaskDiagnosticExcerpt: getExcerpt }));
const evidence = (overrides: Partial<TaskDiagnostics> = {}): TaskDiagnostics => ({
  task_id: 'a'.repeat(32), availability: 'available', summary: 'Execution failed.', reason_code: 'nonzero_exit',
  exit_code: 2, exit_code_source: 'srun', scheduler_state: null, stage: 'fit', logs: [], ...overrides,
});
const excerptUrl = '/compute/api/tasks/' + 'a'.repeat(32) + '/diagnostics/stderr';
const excerptLog = (overrides: Partial<TaskDiagnostics['logs'][number]> = {}): TaskDiagnostics['logs'][number] => ({
  stream: 'stderr', preview: 'step 1\nERROR: again\n', truncated: true, download_url: excerptUrl, ...overrides,
});
let host: HarnessNode;
beforeEach(() => {
  installHarness(vi.stubGlobal); host = document.createElement('section') as unknown as HarnessNode;
  getDiagnostics.mockReset(); getExcerpt.mockReset();
});
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

async function openExcerpt(text = 'boot\nERROR: bad grid\nstep 1\nERROR: again\n'): Promise<void> {
  getDiagnostics.mockResolvedValue(evidence({ logs: [excerptLog()] }));
  getExcerpt.mockResolvedValue(text);
  mountTaskDiagnostics(host as unknown as HTMLElement, 'a'.repeat(32), new AbortController().signal);
  await vi.waitFor(() => expect(host.querySelector('button')).not.toBeNull());
  host.querySelector('button')!.dispatch('click', {});
  await vi.waitFor(() => expect(host.querySelectorAll('.task-diagnostic-line').length).toBeGreaterThan(0));
}

it('loads the retained excerpt only on request and keeps excerpt-relative line numbers', async () => {
  await openExcerpt();
  expect(getExcerpt).toHaveBeenCalledWith(excerptUrl, expect.anything());
  expect(host.querySelector('pre')!.hidden).toBe(true);
  const gutters = host.querySelectorAll('.task-diagnostic-gutter').map(node => node.textContent);
  expect(gutters).toEqual(['1', '2', '3', '4']);
  expect(host.textContent).toContain('Line numbers are relative');
  expect(host.textContent).toContain('ERROR: bad grid');
});

it('searches literally, counts matches and navigates by button and keyboard', async () => {
  await openExcerpt();
  const input = host.querySelector('input') as unknown as HarnessNode & { value: string };
  input.value = 'error';
  input.dispatch('input', {});
  expect(host.querySelectorAll('mark')).toHaveLength(2);
  expect(host.textContent).toContain('Match 1 of 2');
  const buttons = host.querySelectorAll('button');
  buttons[2]!.dispatch('click', {});  // next
  expect(host.textContent).toContain('Match 2 of 2');
  input.dispatch('keydown', { key: 'Enter', shiftKey: false, preventDefault: () => undefined });
  expect(host.textContent).toContain('Match 1 of 2');
  input.dispatch('keydown', { key: 'Enter', shiftKey: true, preventDefault: () => undefined });
  expect(host.textContent).toContain('Match 2 of 2');
  input.dispatch('keydown', { key: 'Escape', preventDefault: () => undefined });
  expect(input.value).toBe('');
  expect(host.querySelectorAll('mark')).toHaveLength(0);
});

it('renders CR and CRLF line endings as separate excerpt lines', async () => {
  await openExcerpt('progress 0%\rprogress 50%\rprogress 100%\r\nnext-real-line\n');
  const gutters = host.querySelectorAll('.task-diagnostic-gutter').map(node => node.textContent);
  expect(gutters).toEqual(['1', '2', '3', '4']);
  expect(host.textContent).not.toContain('\r');
});

it('treats regular-expression metacharacters as literal text', async () => {
  await openExcerpt('a.b\naxb\n');
  const input = host.querySelector('input') as unknown as HarnessNode & { value: string };
  input.value = 'a.b';
  input.dispatch('input', {});
  expect(host.querySelectorAll('mark')).toHaveLength(1);
  expect(host.textContent).toContain('Match 1 of 1');
});

it('keeps the preview and offers the toggle again when the excerpt cannot be loaded', async () => {
  getDiagnostics.mockResolvedValue(evidence({ logs: [excerptLog()] }));
  getExcerpt.mockRejectedValue(new Error('network'));
  mountTaskDiagnostics(host as unknown as HTMLElement, 'a'.repeat(32), new AbortController().signal);
  await vi.waitFor(() => expect(host.querySelector('button')).not.toBeNull());
  host.querySelector('button')!.dispatch('click', {});
  await vi.waitFor(() => expect(host.querySelector('.task-diagnostic-error')!.hidden).toBe(false));
  // The failure sits beside the toggle, not inside the excerpt region that stays
  // hidden until a successful load; a hidden ancestor would hide the feedback.
  expect(host.querySelector('.task-diagnostic-error')!.closest('[hidden]')).toBeNull();
  expect(host.querySelector('pre')!.hidden).toBe(false);
  expect(host.querySelector('button')!.disabled).toBe(false);
});

it('offers no excerpt control when the preview is the whole retained excerpt', async () => {
  getDiagnostics.mockResolvedValue(evidence({ logs: [excerptLog({ truncated: false })] }));
  mountTaskDiagnostics(host as unknown as HTMLElement, 'a'.repeat(32), new AbortController().signal);
  await vi.waitFor(() => expect(host.textContent).toContain('step 1'));
  expect(host.querySelector('button')).toBeNull();
  expect(getExcerpt).not.toHaveBeenCalled();
});

it('renders nothing from an excerpt that resolves after disposal', async () => {
  getDiagnostics.mockResolvedValue(evidence({ logs: [excerptLog()] }));
  let resolveExcerpt!: (value: string) => void;
  getExcerpt.mockImplementationOnce(() => new Promise<string>(done => { resolveExcerpt = done; }));
  const controller = new AbortController();
  mountTaskDiagnostics(host as unknown as HTMLElement, 'a'.repeat(32), controller.signal);
  await vi.waitFor(() => expect(host.querySelector('button')).not.toBeNull());
  host.querySelector('button')!.dispatch('click', {});
  controller.abort(); resolveExcerpt('late retained line\n');
  await Promise.resolve();
  expect(host.textContent).not.toContain('late retained line');
  expect(host.querySelector('.task-diagnostic-error')!.hidden).toBe(true);
});

it('caps highlighted matches and reports the cap', async () => {
  await openExcerpt('x\n'.repeat(1200));
  const input = host.querySelector('input') as unknown as HarnessNode & { value: string };
  input.value = 'x';
  input.dispatch('input', {});
  expect(host.querySelectorAll('mark')).toHaveLength(1000);
  expect(host.textContent).toContain('Match 1 of 1000+');
});

it('renders only the most recent lines of a pathological line-per-byte excerpt', async () => {
  await openExcerpt('a\n'.repeat(10_001));
  expect(host.querySelectorAll('.task-diagnostic-line')).toHaveLength(10_000);
  expect(host.querySelectorAll('.task-diagnostic-gutter')[0]!.textContent).toBe('2');
  expect(host.querySelector('.task-diagnostic-capped')!.hidden).toBe(false);
});
