import type { TaskSummary } from '../../api/app-api';

export type Layout = 'detailed' | 'compact' | 'table';
export interface TaskQuery {
  search: string; regex: boolean; taskType: string; status: string; owner: string;
  submittedFrom: string; submittedTo: string; finishedFrom: string; finishedTo: string;
  sort: 'submitted' | 'finished'; layout: Layout;
}
export interface TaskQueryResult { tasks: TaskSummary[]; error: string | null }
export const initialTaskQuery = (): TaskQuery => ({ search: '', regex: false, taskType: '', status: '', owner: '', submittedFrom: '', submittedTo: '', finishedFrom: '', finishedTo: '', sort: 'submitted', layout: 'detailed' });

function day(value: string | null): string { return value ? value.slice(0, 10) : ''; }
function matcher(value: string, regex: boolean): ((candidate: string | null) => boolean) | null {
  if (!value.trim()) return () => true;
  if (!regex) { const needle = value.trim().toLowerCase(); return candidate => (candidate || '').toLowerCase().includes(needle); }
  try { const expression = new RegExp(value, 'i'); return candidate => expression.test(candidate || ''); } catch { return null; }
}

export function queryTasks(tasks: TaskSummary[], query: TaskQuery): TaskQueryResult {
  const name = matcher(query.search, query.regex), type = matcher(query.taskType, false), owner = matcher(query.owner, false);
  if (!name) return { tasks: [], error: 'Invalid regular expression' };
  const filtered = tasks.filter(task => {
    const submitted = day(task.submitted_at), finished = day(task.finished_at);
    return name(task.display_name) && type!(task.task_type) && owner!(task.owner) && (!query.status || task.status === query.status)
      && (!query.submittedFrom || submitted >= query.submittedFrom) && (!query.submittedTo || submitted <= query.submittedTo)
      && (!query.finishedFrom || (finished && finished >= query.finishedFrom)) && (!query.finishedTo || (finished && finished <= query.finishedTo));
  });
  filtered.sort((a, b) => {
    const left = Date.parse(query.sort === 'finished' ? a.finished_at || '' : a.submitted_at || '') || 0;
    const right = Date.parse(query.sort === 'finished' ? b.finished_at || '' : b.submitted_at || '') || 0;
    return right - left || a.display_name.localeCompare(b.display_name);
  });
  return { tasks: filtered, error: null };
}
