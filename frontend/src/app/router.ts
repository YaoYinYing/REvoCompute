export type AppRoute =
  | { id: 'home' }
  | { id: 'api-docs' }
  | { id: 'login' }
  | { id: 'register' }
  | { id: 'reset-password' }
  | { id: 'verify-email' }
  | { id: 'terms' }
  | { id: 'runners' }
  | { id: 'runner-detail'; name: string }
  | { id: 'dashboard' }
  | { id: 'create-task' }
  | { id: 'result'; taskId: string }
  | { id: 'profile' }
  | { id: 'admin-fleet' }
  | { id: 'admin-users' }
  | { id: 'admin-configuration' }
  | { id: 'admin-logs' }
  | { id: 'not-found' };

const taskIdPattern = /^[a-f0-9]{32}$/i;

export function resolveRoute(pathname: string): AppRoute {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  if (path === '/') return { id: 'home' };
  if (path === '/api-docs') return { id: 'api-docs' };
  if (path === '/compute/login') return { id: 'login' };
  if (path === '/compute/register') return { id: 'register' };
  if (path === '/compute/reset_password') return { id: 'reset-password' };
  if (path === '/compute/user_verify') return { id: 'verify-email' };
  if (path === '/compute/terms') return { id: 'terms' };
  if (path === '/runners') return { id: 'runners' };
  if (path === '/compute/dashboard') return { id: 'dashboard' };
  if (path === '/compute/create_task') return { id: 'create-task' };
  if (path === '/compute/profile') return { id: 'profile' };
  if (path === '/compute/runner_fleet') return { id: 'admin-fleet' };
  if (path === '/compute/user_control') return { id: 'admin-users' };
  if (path === '/compute/configuration') return { id: 'admin-configuration' };
  if (path === '/compute/logs') return { id: 'admin-logs' };
  const runner = /^\/runners\/([^/]+)$/.exec(path);
  if (runner?.[1]) {
    try { return { id: 'runner-detail', name: decodeURIComponent(runner[1]) }; }
    catch { return { id: 'not-found' }; }
  }
  const result = /^\/compute\/results\/([^/]+)$/.exec(path);
  if (result?.[1] && taskIdPattern.test(result[1])) return { id: 'result', taskId: result[1].toLowerCase() };
  return { id: 'not-found' };
}

const protectedRoutes = new Set<AppRoute['id']>([
  'dashboard', 'create-task', 'result', 'profile', 'admin-fleet', 'admin-users', 'admin-configuration', 'admin-logs',
]);
const publicShellRoutes = new Set<AppRoute['id']>([
  'home', 'api-docs', 'login', 'register', 'reset-password', 'verify-email', 'terms', 'not-found',
]);

export const protectedRoute = (route: AppRoute): boolean => protectedRoutes.has(route.id);
export const adminRoute = (route: AppRoute): boolean =>
  route.id === 'admin-fleet' || route.id === 'admin-users' || route.id === 'admin-configuration' || route.id === 'admin-logs';
export const publicShellRoute = (route: AppRoute): boolean => publicShellRoutes.has(route.id);
