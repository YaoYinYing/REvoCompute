import { describe, expect, it } from 'vitest';
import type { TaskSummary } from '../src/api/app-api';
import { initialTaskQuery, queryTasks } from '../src/features/dashboard/task-query';

const task = (overrides: Partial<TaskSummary>): TaskSummary => ({
  task_id: 'a'.repeat(32), task_type: 'example', display_name: 'model.fasta', status: 'finished', terminal: true,
  submitted_at: '2026-09-20T10:00:00Z', finished_at: '2026-09-20T10:01:00Z', walltime_seconds: 60,
  owner: 'owner', progress: null, outcome: 'SUCCESS', error: null,
  result: { available: true, publication: 'available', page_url: '/result', manifest_url: '/manifest', archive_ready: false, archive_request_allowed: true, archive_request_url: '/archive', download_url: null },
  actions: { cancel: { allowed: false, url: '/cancel' }, delete: { allowed: true, url: '/delete' } }, input_preview: null,
  ...overrides,
});

describe('dashboard task query', () => {
  const tasks = [
    task({ task_id: 'a'.repeat(32), display_name: 'Alpha model', task_type: 'alphafold3', owner: 'ada' }),
    task({ task_id: 'b'.repeat(32), display_name: 'Docking run', task_type: 'vina', owner: 'grace', status: 'running', terminal: false, submitted_at: '2026-09-22T10:00:00Z', finished_at: null }),
  ];

  it('combines text, domain, status, owner, and date filters', () => {
    const query = { ...initialTaskQuery(), search: 'dock', taskType: 'vin', owner: 'gra', status: 'running', submittedFrom: '2026-09-21' };
    expect(queryTasks(tasks, query).tasks.map(item => item.task_id)).toEqual(['b'.repeat(32)]);
  });

  it('supports regular expressions and reports invalid expressions', () => {
    expect(queryTasks(tasks, { ...initialTaskQuery(), search: '^Alpha', regex: true }).tasks).toHaveLength(1);
    expect(queryTasks(tasks, { ...initialTaskQuery(), search: '[', regex: true })).toEqual({ tasks: [], error: 'Invalid regular expression' });
  });

  it('sorts missing finish dates deterministically', () => {
    expect(queryTasks(tasks, { ...initialTaskQuery(), sort: 'finished' }).tasks.map(item => item.display_name)).toEqual(['Alpha model', 'Docking run']);
  });

  it('defaults to the detailed task layout', () => {
    expect(initialTaskQuery().layout).toBe('detailed');
  });
});
