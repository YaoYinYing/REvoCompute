import { ApiError, sessionExpiredEvent } from './app/session';
import { getSession, type CurrentUser } from './api/app-api';
import { adminRoute, interceptableLink, protectedRoute, publicShellRoute, resolveRoute, type AppRoute } from './app/router';
import { mountPublicShell } from './app/public-shell';
import { mountShell, type AppShell } from './app/shell';
import { applyLocale, initialLocale, t } from './app/i18n';
import { applyTheme, storedTheme } from './app/theme';
import './styles/app.css';

/*
 * One document, one shell, many routes.
 *
 * The application is a single persistent shell. The shell — brand, top bar, left
 * navigation, main region and the feedback column — is mounted exactly once and
 * never rebuilt by navigation; only the main region's content is unmounted and
 * remounted per route. Every route owns its own `AbortController` and its
 * teardown, so a route change cancels that route's in-flight work and disposes
 * whatever it mounted (a molecular viewer, a poll, a fetch) before the next route
 * begins.
 *
 * Navigation is the History API. A qualifying same-origin in-app link click is
 * intercepted; everything else — middle click, modifier click, download, external
 * link, fragment, sign-in redirect, deep link, refresh, back/forward — is the
 * browser's own behavior. The server still serves the same entry document for
 * every page route, so a refresh or a shared deep link lands on a real page.
 */

type RouteView = { destroy?(): void } | void | null;

const root = document.querySelector<HTMLElement>('#app');
if (!root) throw new Error('Missing frontend application root');

applyTheme(storedTheme());
applyLocale(initialLocale(), false);

const firstRoute = resolveRoute(location.pathname);
// The document has two chromes: the public one for the reference and account
// entry pages, the authenticated one for the workspaces. Which one is mounted is
// a function of the current route, not of how the document was first loaded: the
// public navigation links to /runners and the brand links home, so a reader can
// cross the boundary in one click. Crossing it remounts the chrome — the router
// stays the same, the session stays the same — rather than stranding a workspace
// inside the public header.
let mountedPublic = publicShellRoute(firstRoute);
let shell: AppShell = mountedPublic ? mountPublicShell(root) : mountShell(root);

let currentRoute: AppRoute = firstRoute;
let currentView: RouteView = null;
let currentController = new AbortController();
let renderGeneration = 0;
let firstRender = true;
// The session is read once per document and re-read only when a view reports a
// change. It is one source of truth: no second router and no duplicate auth state.
let sessionUser: CurrentUser | null = null;
let sessionLoaded = false;

/** The location the outlet is committed to. A traversal that lands on exactly
 *  this document is the same page: there is nothing to remount, only a fragment
 *  to honor. A traversal that lands anywhere else is a route change like any
 *  other, so no history-index bookkeeping is needed to tell back from forward.
 *  It is written when a mount starts rather than when it finishes: a mount
 *  awaits its data, and the entry can move while that is in flight. */
let renderedLocation = '';

function reportError(error: unknown): void {
  console.error('REvoCompute route failed', error);
  document.title = `${t('page.error.title')} | REvoCompute`;
  shell.outlet.replaceChildren(errorSection(t('page.error.title'), t('page.error.body')));
  shell.notify((error as Error)?.message || t('page.error.notice'), 'error');
}

function errorSection(title: string, body: string, code = ''): HTMLElement {
  // The error is a page: it owns the document's single main landmark like any
  // other route, so a screen-reader user still lands in the content region.
  const section = document.createElement('main');
  section.className = 'route-error';
  if (code) { const kicker = document.createElement('p'); kicker.className = 'page-kicker'; kicker.textContent = code; section.append(kicker); }
  const heading = document.createElement('h1'); heading.textContent = title;
  const paragraph = document.createElement('p'); paragraph.textContent = body;
  const link = document.createElement('a'); link.className = 'secondary-button'; link.href = '/compute/dashboard'; link.textContent = t('page.error.action');
  section.append(heading, paragraph, link);
  return section;
}

function accessDenied(): void {
  document.title = `${t('page.denied.title')} | REvoCompute`;
  shell.outlet.replaceChildren(errorSection(t('page.denied.title'), t('page.denied.body'), '403'));
  focusHeading();
}

function notFound(): void {
  document.title = `${t('page.notFound.title')} | REvoCompute`;
  shell.outlet.replaceChildren(errorSection(t('page.notFound.title'), t('page.notFound.body'), '404'));
  focusHeading();
}

/**
 * Move focus to the page's own heading after a route change.
 *
 * A screen-reader user who follows a link is moved to the new page's identity,
 * not left where the old page's control used to be. The move only happens when
 * focus was not already inside a text field: an in-page history navigation that
 * updates a filter must never pull the caret out of what the reader is typing.
 *
 * When there is no heading the main region itself takes focus, so a
 * route-without-a-heading still lands the reader in the content.
 */
function focusHeading(historyNavigation = false): void {
  const active = document.activeElement;
  if (historyNavigation && active instanceof HTMLElement && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT' || active.isContentEditable)) return;
  if (active instanceof HTMLElement && shell.outlet.contains(active)) return;
  const heading = shell.outlet.querySelector<HTMLElement>('h1, [role="heading"][aria-level="1"]');
  const target = heading || shell.outlet;
  if (heading) heading.setAttribute('tabindex', '-1');
  // Focus without scrolling: the shell scrolls to the top itself, and a heading
  // focus must not fight a fragment or a restored scroll offset.
  if (!historyNavigation) window.scrollTo({ top: 0, behavior: 'auto' });
  target.focus({ preventScroll: true });
}

/**
 * Name the document after the page the reader is now on.
 *
 * The document title is shared chrome: it belongs to the tab, the history entry
 * and a screen reader's page announcement, not to one page. A feature that names
 * itself during its own mount — a method reference, a legal document, the Account
 * — keeps that name; every other page is named here from its own level-one
 * heading, so no route ever leaves the previous page's name behind.
 */
function nameDocument(previousTitle: string): void {
  if (document.title !== previousTitle) return;
  const heading = shell.outlet.querySelector<HTMLElement>('h1, [role="heading"][aria-level="1"]');
  const name = heading?.textContent?.trim();
  document.title = name ? `${name} | REvoCompute` : 'REvoCompute';
}

function announceHistoryNavigation(): void {
  const region = document.createElement('div');
  region.className = 'sr-only';
  region.setAttribute('aria-live', 'polite');
  region.dataset.routeAnnouncement = '';
  region.textContent = `${t('shell.pageLabel')}: ${document.title}`;
  document.body.append(region);
  window.setTimeout(() => region.remove(), 1200);
}

function session(): Promise<CurrentUser | null> {
  if (sessionLoaded) return Promise.resolve(sessionUser);
  sessionLoaded = true;
  return getSession()
    .then(user => { sessionUser = user; shell.setUser(user); return user; })
    .catch(error => {
      sessionLoaded = false;
      if (error instanceof ApiError && error.status === 401) { sessionUser = null; shell.setUser(null); return null; }
      throw error;
    });
}

function redirectToLogin(): void {
  location.assign(`/compute/login?return_to=${encodeURIComponent(location.pathname + location.search + location.hash)}`);
}

/**
 * Mount the chrome the route belongs to, remounting only when the class changes.
 *
 * Within one chrome the shell is persistent: navigation swaps the outlet's
 * content and nothing else. Crossing between the public pages and the workspaces
 * is not navigation within a shell — the two chromes are different surfaces — so
 * that one crossing mounts the other chrome. The router, the session and the
 * history are unchanged by it; only the chrome is replaced.
 */
const syncShell = (route: AppRoute): void => {
  const wantsPublic = publicShellRoute(route);
  if (wantsPublic === mountedPublic) return;
  mountedPublic = wantsPublic;
  shell = wantsPublic ? mountPublicShell(root) : mountShell(root);
  // The fresh chrome starts from the session the document already resolved rather
  // than from an empty one, so it never briefly paints another reader's
  // affordances; if the session has not resolved yet the chrome reads it itself.
  if (sessionLoaded) shell.setUser(sessionUser);
  else void session().catch(() => shell.setUser(null));
};

/** Mount the route's own content into the persistent outlet, replacing the last. */
async function render(route: AppRoute, historyNavigation: boolean): Promise<void> {
  const generation = ++renderGeneration;
  const previousTitle = document.title;
  currentController.abort();
  currentController = new AbortController();
  currentView?.destroy?.();
  currentView = null;
  // The outlet is shared by every route, so each mount must start from the shell's
  // own class and an empty region: a page that styles the outlet (the Dashboard
  // grid) must not leave its layout on the next page. The router is the one owner
  // of that reset.
  shell.outlet.className = 'app-outlet';
  shell.outlet.replaceChildren();
  // The location this render is mounting is recorded when the mount starts, not
  // when it finishes. A route's mount awaits its own data, and the entry can move
  // while that is in flight; if the record still named the previous page, the
  // traversal that moved it would be read as "the page already on screen" and
  // dropped, leaving the older route's content under the newer address.
  renderedLocation = location.pathname + location.search;

  if (route.id === 'not-found') { notFound(); return; }
  syncShell(route);
  const needsSession = protectedRoute(route) || !mountedPublic;
  if (needsSession) {
    const user = await session();
    if (generation !== renderGeneration) return;
    if (protectedRoute(route) && !user) { redirectToLogin(); return; }
    if (adminRoute(route) && user?.role !== 'admin') { accessDenied(); return; }
  }

  switch (route.id) {
    case 'home': { const { mountHome } = await import('./features/home/index.js'); mountHome(shell.outlet, shell); break; }
    case 'api-docs': { const { mountApiDocs } = await import('./features/api-docs/index.js'); mountApiDocs(shell.outlet); break; }
    case 'login': { const { mountLogin } = await import('./features/auth/index.js'); mountLogin(shell.outlet, shell); break; }
    case 'register': { const { mountRegister } = await import('./features/auth/index.js'); await mountRegister(shell.outlet); break; }
    case 'reset-password': { const { mountResetPassword } = await import('./features/auth/index.js'); mountResetPassword(shell.outlet); break; }
    case 'verify-email': { const { mountVerifyEmail } = await import('./features/auth/index.js'); await mountVerifyEmail(shell.outlet); break; }
    case 'terms': { const { mountTerms } = await import('./features/legal/index.js'); await mountTerms(shell.outlet); break; }
    case 'runners': { const { mountRunnerCatalog } = await import('./features/runners/index.js'); await mountRunnerCatalog(shell.outlet); break; }
    case 'runner-detail': { const { mountRunnerDetail } = await import('./features/runners/index.js'); await mountRunnerDetail(shell.outlet, route.name, shell); break; }
    case 'dashboard': { const { mountDashboard } = await import('./features/dashboard/index.js'); currentView = await mountDashboard(shell.outlet, shell, sessionUser!); break; }
    case 'create-task': { const { mountCreateTask } = await import('./features/create-task/index.js'); await mountCreateTask(shell.outlet); break; }
    case 'result': { const { mountResultWorkspace } = await import('./features/results/index.js'); currentView = await mountResultWorkspace(shell.outlet); break; }
    case 'account': { const { mountAccount } = await import('./features/profile/index.js'); await mountAccount(shell.outlet, shell, sessionUser!, route.section); break; }
    case 'admin-fleet': case 'admin-users': case 'admin-configuration': case 'admin-logs': {
      const { mountAdmin } = await import('./features/admin/index.js'); await mountAdmin(shell.outlet, route.id, shell, sessionUser!); break;
    }
  }
  // A route's mount is asynchronous, and a feature's own fetch is not guaranteed to
  // honor the route's AbortController: a mount that lost the race can resolve after
  // a newer route has rendered and write its content into the outlet on top of it.
  // The address bar is the authoritative record of where the reader is, so a mount
  // that lost the race rebuilds the page the location now names.
  if (generation !== renderGeneration) {
    if (location.pathname + location.search !== renderedLocation) void transition(resolveRoute(location.pathname), new URL(location.href), true);
    return;
  }
  nameDocument(previousTitle);
  shell.syncActive();
  // The document's own first render keeps the browser's initial focus and scroll;
  // a later route change moves the reader to the new page's heading.
  if (!firstRender) focusHeading(historyNavigation);
  firstRender = false;
  if (historyNavigation) announceHistoryNavigation();
}

/** Route to a new location: the one place a URL change enters the application. */
function navigate(url: string, options: { replace?: boolean } = {}): void {
  const target = new URL(url, location.origin);
  const next = `${target.pathname}${target.search}${target.hash}`;
  // The entry holds no application state the browser needs to restore: the route
  // is derived from the location itself, so a restored or shared URL always resolves.
  if (options.replace) history.replaceState(null, '', next);
  else history.pushState(null, '', next);
  void transition(resolveRoute(target.pathname), target, false);
}

/** Render the route the location now holds. Shared by link navigation, back/forward and start. */
async function transition(route: AppRoute, target: URL, historyNavigation: boolean): Promise<void> {
  const samePage = target.pathname === location.pathname;
  currentRoute = route;
  // A fragment on the page being read is a scroll, not a route change: keep the
  // mounted view and let the browser move to the anchor.
  if (samePage && target.hash && shell.outlet.querySelector(`[id="${CSS.escape(target.hash.slice(1))}"]`)) {
    const anchor = shell.outlet.querySelector<HTMLElement>(`[id="${CSS.escape(target.hash.slice(1))}"]`);
    anchor?.scrollIntoView();
    anchor?.focus?.({ preventScroll: true });
    return;
  }
  try { await render(route, historyNavigation); }
  catch (error) { if ((error as Error).name !== 'AbortError') reportError(error); }
}

// A qualifying in-app link is intercepted once, at the document, so the
// persistent shell and every feature-minted anchor share one policy.
document.addEventListener('click', event => {
  if (event.defaultPrevented) return;
  const anchor = (event.target as Element | null)?.closest?.('a[href]');
  if (!(anchor instanceof HTMLAnchorElement)) return;
  if (!interceptableLink(event, anchor)) return;
  event.preventDefault();
  navigate(anchor.href);
});

window.addEventListener('popstate', () => {
  // Back/forward is the browser moving the current entry through its own stack.
  // A traversal that lands back on the location the outlet already holds is the
  // same page: there is nothing to remount, only a fragment (if any) to honor.
  // A fragment inside a page the reader is already on never remounts the page; the
  // browser's own anchor behavior scrolls it.
  if (location.pathname + location.search === renderedLocation) {
    if (location.hash) { const anchor = shell.outlet.querySelector<HTMLElement>(`[id="${CSS.escape(location.hash.slice(1))}"]`); anchor?.scrollIntoView(); }
    return;
  }
  void transition(resolveRoute(location.pathname), new URL(location.href), true);
});

window.addEventListener('pagehide', event => { if (!(event as PageTransitionEvent).persisted) disposeCurrent(); });

function disposeCurrent(): void {
  currentView?.destroy?.();
  currentView = null;
  currentController.abort();
  shell.outlet.replaceChildren();
}

window.addEventListener(sessionExpiredEvent, redirectToLogin);

async function start(): Promise<void> {
  if (mountedPublic) {
    // The public shell still resolves its session so its sign-in affordance
    // reflects a reader who is already authenticated.
    void session().catch(() => undefined);
  }
  await transition(currentRoute, new URL(location.href), false);
}

start().catch(error => {
  if ((error as Error).name === 'AbortError') return;
  reportError(error);
});
