import { ApiError, sessionExpiredEvent } from './app/session';
import { getSession, type CurrentUser } from './api/app-api';
import { resolveRoute, protectedRoute } from './app/router';
import { mountShell } from './app/shell';
import { applyTheme, storedTheme } from './app/theme';
import './styles/app.css';

const root = document.querySelector<HTMLElement>('#app');

if (!root) throw new Error('Missing frontend application root');

applyTheme(storedTheme());
const route = resolveRoute(location.pathname);
const shell = mountShell(root);

window.addEventListener(sessionExpiredEvent, () => {
  location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname + location.search)}`);
});

async function session(): Promise<CurrentUser | null> {
  try { const user = await getSession(); shell.setUser(user); return user; }
  catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      shell.setUser(null);
      if (protectedRoute(route)) location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname + location.search)}`);
      return null;
    }
    if (!protectedRoute(route)) { shell.setUser(null); shell.notify('Session status is temporarily unavailable.', 'error'); return null; }
    throw error;
  }
}

async function start(): Promise<void> {
  const user = await session(); if (protectedRoute(route) && !user) return;
  switch (route.id) {
    case 'runners': {
      const { mountRunnerCatalog } = await import('./features/runners/index.js'); await mountRunnerCatalog(shell.outlet); break;
    }
    case 'runner-detail': {
      const { mountRunnerDetail } = await import('./features/runners/index.js'); await mountRunnerDetail(shell.outlet, route.name, shell); break;
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
    default: {
      shell.outlet.innerHTML = '<section class="route-error"><p class="page-kicker">404</p><h1>Page not found</h1><p>The requested REvoCompute route does not exist.</p><a class="primary-button" href="/runners">Browse runners</a></section>';
    }
  }
}

start().catch(error => { console.error('Unable to start REvoCompute', error); shell.outlet.innerHTML = '<section class="route-error"><h1>Unable to load this view</h1><p>Please refresh or return to the dashboard.</p></section>'; shell.notify((error as Error).message || 'Application startup failed.', 'error'); });
