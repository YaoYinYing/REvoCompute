import { ApiError, sessionExpiredEvent } from './app/session';
import { getSession, type CurrentUser } from './api/app-api';
import { adminRoute, protectedRoute, publicShellRoute, resolveRoute, type AppRoute } from './app/router';
import { mountPublicShell } from './app/public-shell';
import { mountShell, type AppShell } from './app/shell';
import { applyLocale, initialLocale, t } from './app/i18n';
import { applyTheme, storedTheme } from './app/theme';
import './styles/app.css';

const root = document.querySelector<HTMLElement>('#app');

if (!root) throw new Error('Missing frontend application root');

applyTheme(storedTheme());
applyLocale(initialLocale(), false);
const route = resolveRoute(location.pathname);
const shell = publicShellRoute(route) ? mountPublicShell(root) : mountShell(root);

window.addEventListener(sessionExpiredEvent, () => {
  location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname + location.search + location.hash)}`);
});

async function session(shellInstance: AppShell, activeRoute: AppRoute): Promise<CurrentUser | null> {
  try { const user = await getSession(); shellInstance.setUser(user); return user; }
  catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      shellInstance.setUser(null);
      if (protectedRoute(activeRoute)) location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname + location.search + location.hash)}`);
      return null;
    }
    if (!protectedRoute(activeRoute)) { shellInstance.setUser(null); return null; }
    throw error;
  }
}

async function renderRoute(activeRoute: AppRoute, user: CurrentUser | null): Promise<void> {
  switch (activeRoute.id) {
    case 'home': {
      const { mountHome } = await import('./features/home/index.js'); mountHome(shell.outlet, shell); break;
    }
    case 'api-docs': {
      const { mountApiDocs } = await import('./features/api-docs/index.js'); mountApiDocs(shell.outlet); break;
    }
    case 'login': {
      const { mountLogin } = await import('./features/auth/index.js'); mountLogin(shell.outlet, shell); break;
    }
    case 'register': {
      const { mountRegister } = await import('./features/auth/index.js'); await mountRegister(shell.outlet); break;
    }
    case 'reset-password': {
      const { mountResetPassword } = await import('./features/auth/index.js'); mountResetPassword(shell.outlet); break;
    }
    case 'verify-email': {
      const { mountVerifyEmail } = await import('./features/auth/index.js'); await mountVerifyEmail(shell.outlet); break;
    }
    case 'terms': {
      const { mountTerms } = await import('./features/legal/index.js'); await mountTerms(shell.outlet); break;
    }
    case 'runners': {
      const { mountRunnerCatalog } = await import('./features/runners/index.js'); await mountRunnerCatalog(shell.outlet); break;
    }
    case 'runner-detail': {
      const { mountRunnerDetail } = await import('./features/runners/index.js'); await mountRunnerDetail(shell.outlet, activeRoute.name, shell); break;
    }
    case 'dashboard': {
      const { mountDashboard } = await import('./features/dashboard/index.js'); await mountDashboard(shell.outlet, shell, user!); break;
    }
    case 'create-task': {
      const { mountCreateTask } = await import('./features/create-task/index.js'); await mountCreateTask(shell.outlet); break;
    }
    case 'result': {
      const { mountResultWorkspace } = await import('./features/results/index.js'); await mountResultWorkspace(shell.outlet); break;
    }
    case 'profile': {
      const { mountProfile } = await import('./features/profile/index.js'); await mountProfile(shell.outlet, shell, user!); break;
    }
    case 'admin-fleet': case 'admin-users': case 'admin-configuration': case 'admin-logs': {
      const { mountAdmin } = await import('./features/admin/index.js'); await mountAdmin(shell.outlet, activeRoute.id, shell, user!); break;
    }
    default: {
      document.title = `${t('page.notFound.title')} | REvoCompute`;
      shell.outlet.innerHTML = `<section class="route-error"><p class="page-kicker">404</p><h1>${t('page.notFound.title')}</h1><p>${t('page.notFound.body')}</p><a class="primary-button" href="/runners">${t('page.notFound.action')}</a></section>`;
    }
  }
}

async function start(): Promise<void> {
  const sessionRequest = session(shell, route);
  if (!protectedRoute(route)) {
    await renderRoute(route, null);
    void sessionRequest;
    return;
  }
  const user = await sessionRequest;
  if (!user) return;
  if (adminRoute(route) && user.role !== 'admin') {
    shell.outlet.innerHTML = '<section class="route-error"><p class="page-kicker">403</p><h1>Access denied</h1><p>Administrator access is required for this page.</p><a class="secondary-button" href="/compute/dashboard">Return to dashboard</a></section>';
    return;
  }
  await renderRoute(route, user);
}

start().catch(error => { console.error('Unable to start REvoCompute', error); shell.outlet.innerHTML = '<section class="route-error"><h1>Unable to load this view</h1><p>Refresh the page or return to the dashboard.</p></section>'; shell.notify((error as Error).message || 'Application startup failed.', 'error'); });
