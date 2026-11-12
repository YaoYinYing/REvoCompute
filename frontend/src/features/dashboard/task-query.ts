import type { TaskPageParams } from '../../api/app-api';

export type Layout = 'detailed' | 'compact' | 'table';

/** The dashboard's filter state. Search is literal text, evaluated by the server. */
export interface TaskQuery {
  search: string; taskType: string; status: string; owner: string;
  submittedFrom: string; submittedTo: string; finishedFrom: string; finishedTo: string;
  sort: 'submitted' | 'finished'; layout: Layout;
}

export const initialTaskQuery = (): TaskQuery => ({
  search: '', taskType: '', status: '', owner: '',
  submittedFrom: '', submittedTo: '', finishedFrom: '', finishedTo: '',
  sort: 'submitted', layout: 'detailed',
});

/** The server expects exact snake_case parameter names, not the UI's field names. */
export function historyParams(query: TaskQuery, cursor?: string, limit?: number): TaskPageParams {
  return {
    limit,
    cursor,
    q: query.search.trim() || undefined,
    task_type: query.taskType.trim() || undefined,
    status: query.status || undefined,
    owner: query.owner.trim() || undefined,
    submitted_from: query.submittedFrom || undefined,
    submitted_to: query.submittedTo || undefined,
    finished_from: query.finishedFrom || undefined,
    finished_to: query.finishedTo || undefined,
    sort: query.sort,
  };
}

/** Whether any filter narrows the server query beyond the default submitted order. */
export function hasActiveFilters(query: TaskQuery): boolean {
  return Boolean(
    query.search.trim() || query.taskType.trim() || query.status || query.owner.trim()
    || query.submittedFrom || query.submittedTo || query.finishedFrom || query.finishedTo
    || query.sort !== 'submitted',
  );
}
