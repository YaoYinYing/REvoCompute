import { DAYLIGHT_MARK } from './assets';
import { Bell, ChartLine, FileText, Gauge, KeyRound, LayoutDashboard, LogOut, PanelLeft, PanelLeftClose, Plus, Scale, ServerCog, Settings, ShieldCheck, UserCog, UserRound, UsersRound, Workflow, createIcons } from 'lucide';
import type { CurrentUser } from '../api/app-api';
import { authorizedJson, clearSessionCredential } from './session';
import { ADMIN_DESTINATIONS } from './admin-destinations';
import { applyLocale, locale, t } from './i18n';
import { languageMenu, themeButton } from './localize';
import { mountSystemNotices } from './system-notices';

export interface AppShell {
  outlet: HTMLElement;
  notify(message: string, tone?: 'info' | 'success' | 'error'): void;
  setUser(user: CurrentUser | null): void;
  /** Mark the current destination in the navigation. Called on every route change. */
  syncActive(): void;
  /** Write the current notice count onto the top-bar affordance. */
  refreshNotices(): void;
  /** Release the chrome's own document-level subscriptions when it is replaced. */
  destroy(): void;
}

const railKey = 'revocompute-rail';
type RailState = 'collapsed' | 'expanded';
const shellIcons = {
  Bell, ChartLine, FileText, Gauge, KeyRound, LayoutDashboard, LogOut, PanelLeft, PanelLeftClose, Plus,
  Scale, ServerCog, Settings, ShieldCheck, UserCog, UserRound, UsersRound, Workflow,
};

function storedRail(): RailState { return localStorage.getItem(railKey) === 'expanded' ? 'expanded' : 'collapsed'; }

/** A destination the navigation can reach. */
type NavDestination = [href: string, icon: string, label: string];

/** The current user's own Account sections, reached directly from the navigation. */
const ACCOUNT_DESTINATIONS: ReadonlyArray<NavDestination> = [
  ['/compute/profile', 'user-round', 'shell.account.account'],
  ['/compute/account/security', 'shield-check', 'shell.account.security'],
  ['/compute/account/api-key', 'key-round', 'shell.account.apiKey'],
  ['/compute/account/runner-access', 'user-cog', 'shell.account.runnerAccess'],
  ['/compute/account/gpu-credits', 'gauge', 'shell.account.gpuCredits'],
  ['/compute/account/metrics', 'chart-line', 'shell.account.metrics'],
];

/**
 * The account's own resource position, reached beside the Account sections.
 *
 * The Quota page is the reader's own view, read from the endpoints scoped to
 * them, so it is a destination of the Account region rather than an Account
 * section: it is not one of ``router.ts``'s ``accountSections`` (which are the
 * Account's own sub-pages), it has its own protected route id, and it must not
 * appear in the Frontend/Server section parity set. It shares the region's
 * session semantics: signed out, the region collapses to one sign-in affordance.
 */
const QUOTA_DESTINATION: NavDestination = ['/compute/quota', 'scale', 'shell.account.quota'];

/** In-page workspace navigation shares the shell's destination vocabulary. */
export function accountNavigation(): HTMLElement {
  const navigation = document.createElement('nav'); navigation.className = 'account-navigation';
  navigation.setAttribute('aria-label', t('shell.nav.account'));
  for (const [href, , label] of [...ACCOUNT_DESTINATIONS, QUOTA_DESTINATION]) {
    const link = document.createElement('a'); link.href = href; link.textContent = t(label);
    if (location.pathname === href || (href === '/compute/profile' && location.pathname === '/compute/account/account')) link.setAttribute('aria-current', 'page');
    navigation.append(link);
  }
  return navigation;
}

export function mountShell(root: HTMLElement): AppShell {
  root.replaceChildren();
  applyLocale(locale(), false);

  const shell = document.createElement('div');
  shell.className = 'app-shell';
  shell.dataset.rail = storedRail();

  // The decorative logo and wordmark share one accessible home destination.
  const brand = document.createElement('a'); brand.className = 'app-brand'; brand.href = '/'; brand.setAttribute('aria-label', t('shell.home'));
  const logo = document.createElement('span'); logo.className = 'bench-mark'; logo.innerHTML = DAYLIGHT_MARK;
  const brandText = document.createElement('span'); brandText.textContent = 'REvoCompute'; brand.append(brandText, logo);

  // The navigation is the product's information architecture: Compute, the current
  // user's own Account, and — for an administrator — the Administration workspaces.
  // Each region is a labelled group so the sections stay legible as more surfaces
  // join; the grouping is a rule and a label, not a card. The caption names the
  // region; it is not a document heading, so a screen-reader user reaching the
  // navigation never meets section headings before the page's h1.
  const nav = document.createElement('nav'); nav.className = 'app-nav'; nav.setAttribute('aria-label', t('shell.nav.primary'));
  const navGroup = (region: string, labelKey: string): { element: HTMLElement; caption: HTMLElement; items: HTMLElement } => {
    const element = document.createElement('div'); element.className = 'app-nav-group'; element.dataset.navGroup = region;
    element.setAttribute('role', 'group');
    element.setAttribute('aria-labelledby', `app-nav-group-label-${region}`);
    const caption = document.createElement('span'); caption.id = `app-nav-group-label-${region}`; caption.className = 'app-nav-group-label'; caption.textContent = t(labelKey);
    const items = document.createElement('div'); items.className = 'app-nav-group-items';
    element.append(caption, items);
    return { element, caption, items };
  };
  const groups = {
    compute: navGroup('compute', 'shell.nav.compute'),
    account: navGroup('account', 'shell.nav.account'),
    admin: navGroup('admin', 'shell.nav.administration'),
  };
  groups.admin.element.hidden = true;
  const staticCompute: Array<NavDestination> = [
    ['/runners', 'workflow', t('shell.nav.runners')],
    ['/compute/dashboard', 'layout-dashboard', t('shell.nav.dashboard')],
  ];
  for (const [href, icon, label] of staticCompute) groups.compute.items.append(navLink(href, icon, label));
  // The Account region rests on the session: signed in it reaches the user's own
  // sections directly, signed out it is a single sign-in affordance. The region's
  // links are rebuilt when the session changes, so no link ever points a signed-out
  // reader at a protected page.
  const accountLinks: HTMLAnchorElement[] = [];
  for (const [, , labelKey] of [...ACCOUNT_DESTINATIONS, QUOTA_DESTINATION]) { const link = navLink('', '', ''); link.dataset.labelKey = labelKey; groups.account.items.append(link); accountLinks.push(link); }
  for (const destination of ADMIN_DESTINATIONS) {
    const link = navLink(destination.path, destination.icon, t(destination.label)); groups.admin.items.append(link);
  }
  const secondaryNav = document.createElement('div'); secondaryNav.className = 'app-secondary-nav'; secondaryNav.id = 'app-secondary-nav';
  secondaryNav.append(groups.account.element, groups.admin.element);
  nav.append(groups.compute.element, secondaryNav);

  // A named disclosure exposes the user's Account and authorized Admin destinations.
  const railToggle = document.createElement('button');
  railToggle.type = 'button'; railToggle.className = 'app-rail-toggle'; railToggle.setAttribute('aria-controls', 'app-secondary-nav');
  const foot = document.createElement('div'); foot.className = 'app-nav-foot'; foot.append(railToggle);
  nav.append(foot, secondaryNav);

  const syncRailToggle = (): void => {
    const expanded = shell.dataset.rail === 'expanded';
    railToggle.title = t(expanded ? 'shell.nav.collapse' : 'shell.nav.expand');
    railToggle.setAttribute('aria-label', `${t('shell.nav.more')}: ${railToggle.title}`);
    railToggle.setAttribute('aria-expanded', String(expanded));
    railToggle.innerHTML = `<i data-lucide="${expanded ? 'panel-left-close' : 'panel-left'}" aria-hidden="true"></i><span>${t('shell.nav.more')}</span>`;
    createIcons({ icons: shellIcons, root: railToggle });
  };
  const onRailToggle = (): void => {
    shell.dataset.rail = shell.dataset.rail === 'expanded' ? 'collapsed' : 'expanded';
    localStorage.setItem(railKey, shell.dataset.rail);
    syncRailToggle();
  };
  railToggle.addEventListener('click', onRailToggle);
  const closeNavigation = (): void => {
    if (shell.dataset.rail !== 'expanded') return;
    shell.dataset.rail = 'collapsed'; localStorage.setItem(railKey, 'collapsed'); syncRailToggle();
  };
  const onNavigationKey = (event: KeyboardEvent): void => { if (event.key === 'Escape' && shell.dataset.rail === 'expanded') { closeNavigation(); railToggle.focus(); } };
  const onNavigationOutside = (event: PointerEvent): void => { if (!nav.contains(event.target as Node)) closeNavigation(); };
  document.addEventListener('keydown', onNavigationKey);
  document.addEventListener('pointerdown', onNavigationOutside);

  groups.compute.caption.hidden = true;
  groups.account.caption.hidden = false;

  function navLink(href: string, icon: string, label: string): HTMLAnchorElement {
    const link = document.createElement('a'); link.href = href; link.title = label; link.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i><span>${label}</span>`;
    return link;
  }

  /** Mark the destination the reader is on. The navigation owns this state; the
   *  router only tells it when to re-read the location. */
  function currentDestination(href: string): boolean {
    if (!href) return false;
    const path = new URL(href, location.origin).pathname;
    if (location.pathname === path) return true;
    // A method reference is a detail of the catalog: the catalog stays current.
    return path === '/runners' && location.pathname.startsWith('/runners/');
  }
  const allLinks = (): HTMLAnchorElement[] => [
    ...[...groups.compute.items.children, ...groups.account.items.children, ...groups.admin.items.children] as HTMLAnchorElement[],
  ];
  function syncActiveToLocation(): void {
    for (const link of allLinks()) {
      if (currentDestination(link.getAttribute('href') || '')) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
  }

  const header = document.createElement('header'); header.className = 'app-header';
  const actions = document.createElement('div'); actions.className = 'app-header-actions';
  const noticesButton = document.createElement('button'); noticesButton.type = 'button'; noticesButton.className = 'icon-button app-notice-button'; noticesButton.title = t('shell.action.notices'); noticesButton.setAttribute('aria-label', t('shell.action.notices')); noticesButton.innerHTML = '<i data-lucide="bell" aria-hidden="true"></i>';
  noticesButton.hidden = true;
  // Session utilities remain separate from the destination menu.
  const userLink = document.createElement('a'); userLink.className = 'app-user'; userLink.innerHTML = '<i data-lucide="user-round" aria-hidden="true"></i><span></span>';
  const logout = document.createElement('button'); logout.type = 'button'; logout.className = 'icon-button'; logout.title = t('shell.action.logout'); logout.setAttribute('aria-label', t('shell.action.logout')); logout.hidden = true; logout.innerHTML = '<i data-lucide="log-out" aria-hidden="true"></i>';
  logout.addEventListener('click', async () => {
    logout.disabled = true;
    try { await authorizedJson('/compute/api/auth/logout', { method: 'POST' }); }
    finally { clearSessionCredential(); location.assign('/compute/login'); }
  });
  actions.append(languageMenu(), noticesButton, userLink, logout, themeButton());
  header.append(actions);
  // Create Task is reachable from every authenticated application route.
  const newTask = document.createElement('a'); newTask.href = '/compute/create_task'; newTask.className = 'app-new-task'; newTask.title = t('shell.nav.newTask'); newTask.innerHTML = `<i data-lucide="plus" aria-hidden="true"></i><span>${t('shell.nav.newTask')}</span>`;
  groups.compute.items.append(newTask);

  // The outlet is the persistent content region: it outlives every route, so the
  // skip link has a target that survives navigation. It is not itself a `main`
  // landmark — each page owns its own single `main`, and the shell wrapping them
  // would nest the landmark rather than replace it. The outlet is focusable so a
  // route without a heading still lands the reader in the content.
  const outlet = document.createElement('div'); outlet.className = 'app-outlet'; outlet.id = 'main-content'; outlet.tabIndex = -1;
  const feedback = document.createElement('div'); feedback.className = 'app-feedback';
  const notices = document.createElement('aside'); notices.className = 'app-notices'; notices.setAttribute('aria-live', 'polite');
  feedback.append(notices);

  // The skip link is the first focusable thing in the document; it is only painted
  // once focused, and its target is the persistent main region.
  const skip = document.createElement('a'); skip.className = 'skip-link'; skip.href = '#main-content'; skip.textContent = t('shell.skipToContent');

  shell.append(skip, brand, header, nav, outlet, feedback);
  root.append(shell);
  createIcons({ icons: shellIcons, root: shell });
  syncRailToggle();

  // The notice stack clears wrapping/translated navigation at every content size.
  const chromeResize = new ResizeObserver(() => {
    const height = Math.max(...[brand, nav, header].map(node => node.offsetTop + node.offsetHeight));
    shell.style.setProperty('--app-chrome-height', `${height}px`);
  });
  [brand, nav, header].forEach(node => chromeResize.observe(node));
  const systemNotices = mountSystemNotices({ button: noticesButton, host: feedback });

  const syncAccount = (user: CurrentUser | null): void => {
    const label = t(user ? 'shell.action.profile' : 'shell.action.signIn');
    const identity = user?.full_name || user?.username;
    const href = user ? '/compute/profile' : `/compute/login?return_to=${encodeURIComponent(location.pathname)}`;
    // The Account region is the user's own navigation when signed in and a single
    // sign-in affordance when signed out. The Quota destination is the region's
    // last slot, so its own label follows the sections' from the same table.
    const destinations = [...ACCOUNT_DESTINATIONS, QUOTA_DESTINATION];
    accountLinks.forEach((link, index) => {
      const destination = user ? destinations[index] : null;
      const linkLabel = destination ? t(destination[2]) : label;
      link.hidden = !user && index > 0;
      link.href = destination ? destination[0] : href;
      link.title = linkLabel;
      link.innerHTML = `<i data-lucide="${destination ? destination[1] : 'user-round'}" aria-hidden="true"></i><span>${linkLabel}</span>`;
    });
    userLink.querySelector('span')!.textContent = identity || label;
    userLink.href = href; userLink.title = label;
    userLink.setAttribute('aria-label', identity ? `${label}: ${identity}` : label);
    createIcons({ icons: shellIcons, root: groups.account.element });
    createIcons({ icons: shellIcons, root: userLink });
    syncActiveToLocation();
  };
  syncAccount(null);

  return {
    outlet,
    notify(message, tone = 'info') { const item = document.createElement('div'); item.className = `app-notice notice-${tone}`; item.textContent = message; notices.append(item); setTimeout(() => item.remove(), 4200); },
    setUser(user) {
      syncAccount(user);
      logout.hidden = !user;
      // The bar's one primary page action belongs to a session like Log out does:
      // /compute/create_task is a protected route, so offering it to a signed-out
      // reader would hand them an affordance whose only outcome is a redirect.
      newTask.hidden = !user;
      // Authorization, not visual hiding: the Administration group is absent from
      // the navigation for anyone the server has not projected as an administrator,
      // so an ordinary user or an anonymous visitor never sees a forbidden link.
      groups.admin.element.hidden = user?.role !== 'admin';
      void systemNotices.refresh();
    },
    syncActive() { syncActiveToLocation(); closeNavigation(); },
    refreshNotices() { void systemNotices.refresh(); },
    // The chrome is mounted once per document and replaced only when the reader
    // crosses to the other chrome, which this document now does without a reload.
    // Its document-level subscriptions outlive the nodes they were attached to, so
    // each chrome releases its own before the next one mounts: an unbounded set of
    // listeners and observers would otherwise accumulate across every crossing.
    destroy() {
      chromeResize.disconnect();
      railToggle.removeEventListener('click', onRailToggle);
      document.removeEventListener('keydown', onNavigationKey);
      document.removeEventListener('pointerdown', onNavigationOutside);
    },
  };
}
