import { describe, expect, it } from 'vitest';
import { hasActiveFilters, historyParams, initialTaskQuery } from '../src/features/dashboard/task-query';

describe('dashboard history query', () => {
  it('maps UI fields to the server vocabulary and omits empty filters', () => {
    expect(historyParams(initialTaskQuery(), undefined, 30)).toEqual({
      limit: 30,
      cursor: undefined,
      q: undefined,
      task_type: undefined,
      status: undefined,
      owner: undefined,
      submitted_from: undefined,
      submitted_to: undefined,
      finished_from: undefined,
      finished_to: undefined,
      sort: 'submitted',
    });
    expect(historyParams({
      ...initialTaskQuery(),
      search: ' Alpha ', taskType: 'alphafold3', status: 'running', owner: 'ada',
      submittedFrom: '2026-01-01', finishedTo: '2026-02-01', sort: 'finished',
    }, 'cursor-token', 50)).toMatchObject({
      limit: 50,
      cursor: 'cursor-token',
      q: 'Alpha',
      task_type: 'alphafold3',
      status: 'running',
      owner: 'ada',
      submitted_from: '2026-01-01',
      finished_to: '2026-02-01',
      sort: 'finished',
    });
  });

  it('does not offer a client-side regex or sorting path', () => {
    expect(Object.keys(initialTaskQuery())).not.toContain('regex');
    expect(hasActiveFilters(initialTaskQuery())).toBe(false);
    expect(hasActiveFilters({ ...initialTaskQuery(), search: 'x' })).toBe(true);
    expect(hasActiveFilters({ ...initialTaskQuery(), sort: 'finished' })).toBe(true);
  });
});
