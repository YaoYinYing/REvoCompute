import { ApiError, sessionExpiredEvent } from './app/session';
import { getSession, type CurrentUser } from './api/app-api';
import { adminRoute, interceptableLink, protectedRoute, publicShellRoute, resolveRoute, type AppRoute } from './app/router';
import { mountPublicShell } from './app/public-shell';
import { mountShell, type AppShell } from './app/shell';
import { applyLocale, initialLocale, t } from './app/i18n';
import { GUIDED_TOUR_ABORT_EVENT } from './app/guided-tour';
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

/**
 * A route owns the region it renders into, so it renders into its own node.
 *
 * The router opens a fresh region for every route and hands it to that route's
 * mount, so two mounts never share a node: a mount that is superseded while it is
 * still awaiting its data writes into a region that is no longer in the document
 * rather than over the page the reader is on. Only a mount that is still the
 * reader's route when it settles is kept; one that lost the race is disposed in
 * full, so no viewer, poll or handler outlives the page that created it.
 */
interface RouteMount {
  readonly holder: HTMLElement;
  view: RouteView;
}

/** The signal a route change sends to whatever the leaving page put in the document. */
const tourAbortEvent = GUIDED_TOUR_ABORT_EVENT;

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
/** The content region's own class, owned by the chrome that mounted it. */
let outletBase = shell.outlet.className;

let currentRoute: AppRoute = firstRoute;
// The mount the reader is on, and the mount a route change has begun. A route is
// committed into the outlet only once its own awaits are over, so the two are
// different for exactly as long as a page is being built.
let committedMount: RouteMount | null = null;
let pendingMount: RouteMount | null = null;
let committedTitle = document.title;
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
  shell.outlet.className = outletBase;
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
  shell.outlet.className = outletBase;
  shell.outlet.replaceChildren(errorSection(t('page.denied.title'), t('page.denied.body'), '403'));
  focusHeading();
}

function notFound(): void {
  document.title = `${t('page.notFound.title')} | REvoCompute`;
  shell.outlet.className = outletBase;
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
function nameDocument(): void {
  const heading = shell.outlet.querySelector<HTMLElement>('h1, [role="heading"][aria-level="1"]');
  const name = heading?.textContent?.trim();
  if (name) document.title = `${name} | REvoCompute`;
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
  // The region's class is the chrome's, not the router's: the public chrome names
  // its own region, and the router must not repaint the workspace's class onto it.
  outletBase = shell.outlet.className;
  // The fresh chrome starts from the session the document already resolved rather
  // than from an empty one, so it never briefly paints another reader's
  // affordances; if the session has not resolved yet the chrome reads it itself.
  if (sessionLoaded) shell.setUser(sessionUser);
  else void session().catch(() => shell.setUser(null));
};

/**
 * Render the route the reader is on into a region only that route can write to.
 *
 * A route's mount is asynchronous — it awaits its own module and its own data —
 * and the outlet is one region every route shares. The router therefore opens a
 * fresh region for every mount and keeps it out of the outlet until the mount has
 * settled: whatever a superseded mount does with the route's AbortController, it
 * can only ever write into the region the router gave it, never over the page the
 * reader is on. The region the reader is on stays painted and alive until the new
 * page is complete, and a mount that is no longer the reader's route when it
 * settles is disposed in full — its view, its poll, its region — rather than
 * committed.
 */
async function render(route: AppRoute, historyNavigation: boolean): Promise<void> {
  const generation = ++renderGeneration;
  currentController.abort();
  currentController = new AbortController();
  // Both ends of the route change stop here: the mount a previous render left in
  // flight (it never finished, so it never owned anything the reader saw) and the
  // page the reader is on. A viewer, a poll or a handler gets no further moment.
  if (pendingMount) { destroyMount(pendingMount); pendingMount = null; }
  if (committedMount) { destroyMount(committedMount); committedMount = null; }
  // A route change invalidates what the leaving page put in the document: a
  // guided tour anchors to the page it belongs to, and an in-document route change
  // fires no `pagehide`. The signal is a plain document event, so the navigation
  // layer never has to know which surfaces listen for it. Only a route change
  // dispatched it: a first render is a page arriving, and a document navigation
  // fires `pagehide`, which the same surfaces already hear. A surface that walks
  // its own reader across routes — the tour's own step — therefore keeps working.
  if (generation > 1) document.dispatchEvent(new Event(tourAbortEvent));
  // The region this route renders into. It is created here, owned by this render,
  // and placed in the outlet so the page paints while it builds — but a route that
  // is superseded keeps writing into this region and nothing else, and this region
  // is no longer in the outlet by then. A mount that loses the race therefore
  // cannot repaint the page the reader is on, whatever its own fetch does with the
  // route's AbortController; the same ownership check disposes it in full.
  const mount: RouteMount = { holder: document.createElement('div'), view: null };
  pendingMount = mount;
  // The location this render is mounting is recorded when the mount starts, not
  // when it finishes. A route's mount awaits its own data, and the entry can move
  // while that is in flight; if the record still named the previous page, the
  // traversal that moved it would be read as "the page already on screen" and
  // dropped, leaving the older route's content under the newer address.
  renderedLocation = location.pathname + location.search;

  try {
    if (route.id === 'not-found') { notFound(); return; }
    // Crossing between the public pages and the workspaces remounts the chrome,
    // and a fresh chrome opens with a fresh region, so the mount is staged into
    // the outlet only once the chrome that will carry it is the one mounted.
    syncShell(route);
    shell.outlet.className = outletBase;
    shell.outlet.replaceChildren(mount.holder);
    const needsSession = protectedRoute(route) || !mountedPublic;
    if (needsSession) {
      const user = await session();
      if (generation !== renderGeneration) { destroyMount(mount); restoreTitle(); return; }
      if (protectedRoute(route) && !user) { redirectToLogin(); return; }
      if (adminRoute(route) && user?.role !== 'admin') { accessDenied(); return; }
    }

    switch (route.id) {
      case 'home': { const { mountHome } = await import('./features/home/index.js'); mountHome(mount.holder, shell); break; }
      case 'api-docs': { const { mountApiDocs } = await import('./features/api-docs/index.js'); mountApiDocs(mount.holder); break; }
      case 'login': { const { mountLogin } = await import('./features/auth/index.js'); mountLogin(mount.holder, shell); break; }
      case 'register': { const { mountRegister } = await import('./features/auth/index.js'); await mountRegister(mount.holder); break; }
      case 'reset-password': { const { mountResetPassword } = await import('./features/auth/index.js'); mountResetPassword(mount.holder); break; }
      case 'verify-email': { const { mountVerifyEmail } = await import('./features/auth/index.js'); await mountVerifyEmail(mount.holder); break; }
      case 'terms': { const { mountTerms } = await import('./features/legal/index.js'); await mountTerms(mount.holder); break; }
      case 'runners': { const { mountRunnerCatalog } = await import('./features/runners/index.js'); await mountRunnerCatalog(mount.holder); break; }
      case 'runner-detail': { const { mountRunnerDetail } = await import('./features/runners/index.js'); await mountRunnerDetail(mount.holder, route.name, shell); break; }
      case 'dashboard': { const { mountDashboard } = await import('./features/dashboard/index.js'); const view = mountDashboard(mount.holder, shell, sessionUser!); mount.view = view; await view.load(); break; }
      case 'create-task': { const { mountCreateTask } = await import('./features/create-task/index.js'); await mountCreateTask(mount.holder); break; }
      case 'result': { const { mountResultWorkspace } = await import('./features/results/index.js'); mount.view = await mountResultWorkspace(mount.holder); break; }
      case 'account': { const { mountAccount } = await import('./features/profile/index.js'); await mountAccount(mount.holder, shell, sessionUser!, route.section); break; }
      case 'admin-fleet': case 'admin-users': case 'admin-configuration': case 'admin-logs': {
        const { mountAdmin } = await import('./features/admin/index.js'); await mountAdmin(mount.holder, route.id, shell, sessionUser!); break;
      }
    }
  } catch (error) {
    destroyMount(mount);
    restoreTitle();
    throw error;
  }

  // The mount's own awaits are over: this is where the route becomes the page the
  // reader is on. A mount that stopped being the reader's route while it was
  // building is disposed in full instead, and never presented as their page.
  if (generation !== renderGeneration) { destroyMount(mount); restoreTitle(); return; }
  if (pendingMount === mount) pendingMount = null;
  committedMount = mount;
  // A page that styles the outlet (the Dashboard grid, the catalog's own padding)
  // brings that class with it; the router restates the chrome's own class first.
  const own = mount.holder.className.replace(/(^|\s)app-outlet(\s|$)/g, ' ').trim();
  mount.holder.className = '';
  shell.outlet.className = own ? `${outletBase} ${own}` : outletBase;
  // A page that named itself while mounting keeps that name; every other page is
  // named from its own level-one heading, so no route leaves the last page's name
  // behind on the tab, the history entry or the screen reader's announcement.
  nameDocument();
  committedTitle = document.title;
  shell.syncActive();
  // The document's own first render keeps the browser's initial focus and scroll;
  // a later route change moves the reader to the new page's heading.
  if (!firstRender) focusHeading(historyNavigation);
  firstRender = false;
  if (historyNavigation) announceHistoryNavigation();
}

/**
 * Dispose a mount and everything it built, wherever it is in its life.
 *
 * The view that names its own teardown is asked to run it. Safe to call twice: a
 * view that arrives after the mount was discarded — the route awaited it and then
 * learned it had been superseded — is released on arrival instead of leaking,
 * because the mount keeps asking until there is no view left to own.
 *
 * It announces nothing here. Every route change announces the leaving page once,
 * at its start; a second announcement while the mount is disposed would be heard
 * by that page's own handlers a second time, and a handler that reads the signal
 * as "the reader left me" would end itself on the way out of a navigation it
 * asked for.
 */
function destroyMount(mount: RouteMount): void {
  const view = mount.view;
  mount.view = null;
  if (!view) return;
  (view as { destroy?(): void } | null)?.destroy?.();
}

/** Put the document's name back on the page the reader is actually on. */
function restoreTitle(): void {
  if (document.title !== committedTitle) document.title = committedTitle;
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
  if (pendingMount) destroyMount(pendingMount);
  pendingMount = null;
  if (committedMount) destroyMount(committedMount);
  committedMount = null;
  currentController.abort();
  shell.outlet.className = outletBase;
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
