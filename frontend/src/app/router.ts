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
  | { id: 'local-results' }
  | { id: 'demo' }
  | { id: 'demo-replay'; scenario: string }
  | { id: 'account'; section: AccountSection }
  | { id: 'quota' }
  | { id: 'admin-fleet' }
  | { id: 'admin-users' }
  | { id: 'admin-configuration' }
  | { id: 'admin-logs' }
  | { id: 'not-found' };

/**
 * The sections of the user's own Account, each a page the shell links to
 * directly. The region is a navigation level of its own: the sections are peers
 * reached from the left navigation, never nested tabs inside one Profile page.
 */
export type AccountSection = 'account' | 'security' | 'api-key' | 'runner-access' | 'gpu-credits' | 'metrics';

const taskIdPattern = /^[a-f0-9]{32}$/i;
const accountSections = new Set<string>(['account', 'security', 'api-key', 'runner-access', 'gpu-credits', 'metrics']);

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
  // /compute/profile stays a valid entry point: it is the Account's first
  // section. Every other section has its own address so it can be linked,
  // bookmarked, refreshed, and shared on its own.
  if (path === '/compute/profile') return { id: 'account', section: 'account' };
  const account = /^\/compute\/account\/([^/]+)$/.exec(path);
  if (account?.[1] && accountSections.has(account[1])) return { id: 'account', section: account[1] as AccountSection };
  if (path === '/compute/quota') return { id: 'quota' };
  if (path === '/compute/local_results') return { id: 'local-results' };
  if (path === '/compute/demo') return { id: 'demo' };
  const demoReplay = /^\/compute\/demo\/replays\/([^/]+)$/.exec(path);
  if (demoReplay?.[1]) {
    try { return { id: 'demo-replay', scenario: decodeURIComponent(demoReplay[1]) }; }
    catch { return { id: 'not-found' }; }
  }
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
  'dashboard', 'create-task', 'result', 'local-results', 'demo', 'demo-replay', 'account', 'quota', 'admin-fleet', 'admin-users', 'admin-configuration', 'admin-logs',
]);
const publicShellRoutes = new Set<AppRoute['id']>([
  'home', 'api-docs', 'login', 'register', 'reset-password', 'verify-email', 'terms', 'not-found',
]);

export const protectedRoute = (route: AppRoute): boolean => protectedRoutes.has(route.id);
export const adminRoute = (route: AppRoute): boolean =>
  route.id === 'admin-fleet' || route.id === 'admin-users' || route.id === 'admin-configuration' || route.id === 'admin-logs';
export const publicShellRoute = (route: AppRoute): boolean => publicShellRoutes.has(route.id);

/** The canonical path for a route: the address the browser should hold. */
export function routePath(route: AppRoute): string {
  switch (route.id) {
    case 'home': return '/';
    case 'api-docs': return '/api-docs';
    case 'login': return '/compute/login';
    case 'register': return '/compute/register';
    case 'reset-password': return '/compute/reset_password';
    case 'verify-email': return '/compute/user_verify';
    case 'terms': return '/compute/terms';
    case 'runners': return '/runners';
    case 'runner-detail': return `/runners/${encodeURIComponent(route.name)}`;
    case 'dashboard': return '/compute/dashboard';
    case 'create-task': return '/compute/create_task';
    case 'result': return `/compute/results/${route.taskId}`;
    case 'local-results': return '/compute/local_results';
    case 'demo': return '/compute/demo';
    case 'demo-replay': return `/compute/demo/replays/${encodeURIComponent(route.scenario)}`;
    case 'account': return route.section === 'account' ? '/compute/profile' : `/compute/account/${route.section}`;
    case 'quota': return '/compute/quota';
    case 'admin-fleet': return '/compute/runner_fleet';
    case 'admin-users': return '/compute/user_control';
    case 'admin-configuration': return '/compute/configuration';
    case 'admin-logs': return '/compute/logs';
    default: return location.pathname;
  }
}

/**
 * Whether a same-origin link click is the shell's to intercept.
 *
 * Only a plain left click on an unfragmented link to another in-app page
 * qualifies. Everything the reader can do on purpose — a middle click, a
 * modifier-click that means "open elsewhere", a download, a `target` other than
 * the current context, an external origin, a same-page fragment, or a link that
 * already points at the page being read — keeps the browser's own behavior.
 */
export function interceptableLink(event: MouseEvent, anchor: HTMLAnchorElement): boolean {
  if (event.defaultPrevented || event.button !== 0) return false;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
  if (anchor.target && anchor.target !== '_self') return false;
  if (anchor.hasAttribute('download')) return false;
  const raw = anchor.getAttribute('href');
  if (!raw || raw.startsWith('#')) return false;
  let url: URL;
  try { url = new URL(anchor.href); }
  catch { return false; }
  if (url.origin !== location.origin) return false;
  // A hash is a real destination (a fragment of a document); in-page anchors and
  // the sections that steer by fragment keep native behavior.
  if (url.hash && url.pathname === location.pathname) return false;
  if (url.pathname === location.pathname && url.search === location.search) return false;
  if (resolveRoute(url.pathname).id === 'not-found' && resolveRoute(location.pathname).id !== 'not-found') return false;
  return true;
}
