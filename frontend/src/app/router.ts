export type AppRoute =
  | { id: 'runners' }
  | { id: 'runner-detail'; name: string }
  | { id: 'dashboard' }
  | { id: 'create-task' }
  | { id: 'result'; taskId: string }
  | { id: 'not-found' };

const taskIdPattern = /^[a-f0-9]{32}$/i;

export function resolveRoute(pathname: string): AppRoute {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  if (path === '/runners') return { id: 'runners' };
  if (path === '/compute/dashboard') return { id: 'dashboard' };
  if (path === '/compute/create_task') return { id: 'create-task' };
  const runner = /^\/runners\/([^/]+)$/.exec(path);
  if (runner?.[1]) {
    try { return { id: 'runner-detail', name: decodeURIComponent(runner[1]) }; }
    catch { return { id: 'not-found' }; }
  }
  const result = /^\/compute\/results\/([^/]+)$/.exec(path);
  if (result?.[1] && taskIdPattern.test(result[1])) return { id: 'result', taskId: result[1].toLowerCase() };
  return { id: 'not-found' };
}

export const protectedRoute = (route: AppRoute): boolean => route.id === 'dashboard' || route.id === 'create-task' || route.id === 'result';
