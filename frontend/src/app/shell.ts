import { Bell, Check, createIcons, FileText, Languages, LayoutDashboard, LogOut, MoonStar, Plus, ServerCog, Settings, SunMedium, UserRound, UsersRound, Workflow } from 'lucide';
import type { CurrentUser } from '../api/app-api';
import { authorizedJson, clearSessionCredential } from './session';
import { ADMIN_DESTINATIONS } from './admin-destinations';
import { appAsset } from './assets';
import { applyLocale, locale, locales, setLocale, t, type Locale } from './i18n';
import { cycleTheme, storedTheme, type ThemeMode } from './theme';
import { mountSystemNotices } from './system-notices';

export interface AppShell {
  outlet: HTMLElement;
  notify(message: string, tone?: 'info' | 'success' | 'error'): void;
  setUser(user: CurrentUser | null): void;
}

const railKey = 'revocompute-rail';
type RailState = 'collapsed' | 'expanded';
const shellIcons = { Bell, Check, FileText, Languages, LayoutDashboard, LogOut, MoonStar, Plus, ServerCog, Settings, SunMedium, UserRound, UsersRound, Workflow };

function storedRail(): RailState { return localStorage.getItem(railKey) === 'expanded' ? 'expanded' : 'collapsed'; }
function themeLabel(mode: ThemeMode): string { return `${t('shell.action.theme')}: ${t(`theme.${mode}`)}`; }

/** A destination the left navigation can reach. */
type NavDestination = [href: string, icon: string, label: string];

/** The rail exists only where the left navigation is laid out as a column. On the
 *  mobile bottom bar a repeat activation navigates like any other link. */
const desktopRail = matchMedia('(min-width: 56.01rem)');
/** Above this width the left navigation is grouped into labelled regions. */
const navGrouped = matchMedia('(min-width: 62rem)');

function currentDestination(href: string): boolean {
  return location.pathname === href || (href === '/runners' && location.pathname.startsWith('/runners/'));
}

export function mountShell(root: HTMLElement): AppShell {
  root.replaceChildren();
  applyLocale(locale(), false);

  const shell = document.createElement('div');
  shell.className = 'app-shell';
  shell.dataset.rail = storedRail();

  const brand = document.createElement('a'); brand.className = 'app-brand'; brand.href = '/';
  const logo = document.createElement('img'); logo.src = appAsset('logo.svg'); logo.alt = ''; logo.width = 30; logo.height = 30;
  const brandText = document.createElement('span'); brandText.textContent = 'REvoCompute'; brand.append(logo, brandText);

  // The left navigation is the product's information architecture: Compute, the
  // current user's Account, and — for an administrator — the Administration
  // workspaces. Each region is a labelled group so the sections stay legible as
  // more surfaces join; the grouping is a rule and a label, not a card.
  const nav = document.createElement('nav'); nav.className = 'app-nav'; nav.setAttribute('aria-label', t('shell.nav.primary'));
  const groups = {
    compute: navGroup('compute', 'shell.nav.compute'),
    account: navGroup('account', 'shell.nav.account'),
    admin: navGroup('admin', 'shell.nav.administration'),
  };
  groups.admin.element.hidden = true;
  const destinations: Array<[keyof typeof groups, Array<NavDestination>]> = [
    ['compute', [
      ['/runners', 'workflow', t('shell.nav.runners')],
      ['/compute/dashboard', 'layout-dashboard', t('shell.nav.dashboard')],
    ]],
    // Account is the current user's own identity; Administration is system-level
    // workspaces. They are different navigation levels and never merge into the
    // Profile page's local section tabs.
    ['account', [
      ['/compute/profile', 'user-round', t('shell.nav.profile')],
    ]],
    ['admin', ADMIN_DESTINATIONS.map(destination => [destination.path, destination.icon, t(destination.label)] as NavDestination)],
  ];
  for (const [region, links] of destinations) {
    for (const [href, icon, label] of links) groups[region].items.append(navLink(href, icon, label));
  }
  Object.values(groups).forEach(group => nav.append(group.element));
  // The Account region restates the current user's identity, so it follows the same
  // session state as the top-bar profile affordance — one identity, two reach points.
  const accountLink = groups.account.items.firstElementChild as HTMLAnchorElement;
  // The group label names the region on the desktop rail. On the mobile bar the
  // Compute and Account destinations sit directly on the bar, so their headings are
  // removed from the tree there; the Administration heading is kept because on mobile
  // it names the bounded secondary surface above the bar (see app.css).
  const syncGroupHeadings = (grouped: boolean): void => {
    [groups.compute, groups.account].forEach(group => group.heading.hidden = !grouped);
  };
  syncGroupHeadings(navGrouped.matches);
  navGrouped.addEventListener('change', event => syncGroupHeadings(event.matches));

  function navGroup(region: string, labelKey: string): { element: HTMLElement; heading: HTMLElement; items: HTMLElement } {
    const element = document.createElement('div'); element.className = 'app-nav-group'; element.dataset.navGroup = region;
    // The heading names the region wherever the links are grouped into a column.
    const heading = document.createElement('h2'); heading.className = 'app-nav-group-label'; heading.textContent = t(labelKey);
    const items = document.createElement('div'); items.className = 'app-nav-group-items';
    element.append(heading, items);
    return { element, heading, items };
  }

  function navLink(href: string, icon: string, label: string): HTMLElement {
    const link = document.createElement('a'); link.href = href; link.title = label; link.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i><span>${label}</span>`;
    if (currentDestination(href)) link.setAttribute('aria-current', 'page');
    // Repeated activation of the current item toggles the desktop rail. There is
    // no separate collapse arrow: the control that toggles the rail is the item
    // you are already on. On the mobile bar there is no rail to toggle, so the
    // item navigates like any other.
    link.addEventListener('click', event => {
      if (!desktopRail.matches || !currentDestination(link.pathname)) return;
      event.preventDefault();
      toggleRail();
    });
    return link;
  }

  function toggleRail(): void {
    shell.dataset.rail = shell.dataset.rail === 'expanded' ? 'collapsed' : 'expanded';
    localStorage.setItem(railKey, shell.dataset.rail);
  }

  const header = document.createElement('header'); header.className = 'app-header';
  const actions = document.createElement('div'); actions.className = 'app-header-actions';
  const noticesButton = document.createElement('button'); noticesButton.type = 'button'; noticesButton.className = 'icon-button app-notice-button'; noticesButton.title = t('shell.action.notices'); noticesButton.setAttribute('aria-label', t('shell.action.notices')); noticesButton.innerHTML = '<i data-lucide="bell" aria-hidden="true"></i>';
  noticesButton.hidden = true;
  // The top bar is global chrome only. Administration lives in the left
  // navigation, so it must not also be re-launched from a second hidden menu here.
  const userLink = document.createElement('a'); userLink.className = 'app-user'; userLink.innerHTML = '<i data-lucide="user-round" aria-hidden="true"></i><span></span>';
  const logout = document.createElement('button'); logout.type = 'button'; logout.className = 'icon-button'; logout.title = t('shell.action.logout'); logout.setAttribute('aria-label', t('shell.action.logout')); logout.hidden = true; logout.innerHTML = '<i data-lucide="log-out" aria-hidden="true"></i>';
  logout.addEventListener('click', async () => {
    logout.disabled = true;
    try { await authorizedJson('/compute/api/auth/logout', { method: 'POST' }); }
    finally { clearSessionCredential(); location.assign('/compute/login'); }
  });
  const theme = document.createElement('button'); theme.type = 'button'; theme.className = 'icon-button'; theme.title = themeLabel(storedTheme()); theme.setAttribute('aria-label', theme.title); theme.innerHTML = `<i data-lucide="${document.documentElement.dataset.theme === 'dark' ? 'sun-medium' : 'moon-star'}" aria-hidden="true"></i>`;
  theme.addEventListener('click', () => {
    const mode = cycleTheme(); theme.title = themeLabel(mode); theme.setAttribute('aria-label', theme.title);
    theme.innerHTML = `<i data-lucide="${document.documentElement.dataset.theme === 'dark' ? 'sun-medium' : 'moon-star'}" aria-hidden="true"></i>`;
    createIcons({ icons: { MoonStar, SunMedium }, root: theme });
  });
  actions.append(languageMenu(), noticesButton, userLink, logout, theme);
  header.append(actions);
  // The top bar holds global capability plus one primary page action, so the bar is
  // usable at any width without turning the rail into an IDE toolbar.
  const newTask = document.createElement('a'); newTask.href = '/compute/create_task'; newTask.className = 'app-new-task'; newTask.title = t('shell.nav.newTask'); newTask.innerHTML = `<i data-lucide="plus" aria-hidden="true"></i><span>${t('shell.nav.newTask')}</span>`;
  if (location.pathname === '/compute/create_task') newTask.setAttribute('aria-current', 'page');
  header.prepend(newTask);

  const outlet = document.createElement('div'); outlet.className = 'app-outlet'; outlet.id = 'main-content';
  const feedback = document.createElement('div'); feedback.className = 'app-feedback';
  const notices = document.createElement('aside'); notices.className = 'app-notices'; notices.setAttribute('aria-live', 'polite');
  feedback.append(notices);
  shell.append(brand, header, nav, outlet, feedback);
  root.append(shell);
  createIcons({ icons: shellIcons, root: shell });

  // Measure the secondary surface rather than assuming its height: translated
  // labels and narrow widths can wrap. CSS applies this clearance only on mobile.
  new ResizeObserver(() => {
    shell.style.setProperty('--app-admin-height', `${groups.admin.element.getBoundingClientRect().height}px`);
  }).observe(groups.admin.element);

  const systemNotices = mountSystemNotices({ button: noticesButton, host: feedback });

  const syncAccount = (user: CurrentUser | null): void => {
    const label = t(user ? 'shell.action.profile' : 'shell.action.signIn');
    const identity = user?.full_name || user?.username;
    const href = user ? '/compute/profile' : `/compute/login?return_to=${encodeURIComponent(location.pathname)}`;
    accountLink.querySelector('span')!.textContent = label;
    userLink.querySelector('span')!.textContent = identity || label;
    for (const link of [accountLink, userLink]) {
      link.href = href;
      link.title = label;
      link.setAttribute('aria-label', link === userLink && identity ? `${label}: ${identity}` : label);
      if (currentDestination(link.pathname)) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
  };
  syncAccount(null);

  return {
    outlet,
    notify(message, tone = 'info') { const item = document.createElement('div'); item.className = `app-notice notice-${tone}`; item.textContent = message; notices.append(item); setTimeout(() => item.remove(), 4200); },
    setUser(user) {
      syncAccount(user);
      logout.hidden = !user;
      // Authorization, not visual hiding: the Administration group is absent from
      // the navigation for anyone the server has not projected as an administrator,
      // so an ordinary user or an anonymous visitor never sees a forbidden link.
      groups.admin.element.hidden = user?.role !== 'admin';
      void systemNotices.refresh();
    },
  };
}

function languageMenu(): HTMLElement {
  const details = document.createElement('details'); details.className = 'lang-menu';
  const summary = document.createElement('summary'); summary.className = 'icon-button'; summary.title = t('shell.action.language'); summary.setAttribute('aria-label', t('shell.action.language'));
  const current = locales.find(item => item.id === locale())!;
  summary.innerHTML = `<i data-lucide="languages" aria-hidden="true"></i><span class="lang-menu-value">${current.label}</span>`;
  const options = document.createElement('div'); options.className = 'lang-options'; options.setAttribute('role', 'radiogroup'); options.setAttribute('aria-label', t('shell.action.language'));
  locales.forEach(item => {
    const button = document.createElement('button'); button.type = 'button'; button.setAttribute('role', 'radio'); button.setAttribute('aria-checked', String(item.id === locale()));
    button.dataset.locale = item.id;
    button.append(document.createTextNode(item.label));
    if (item.id === locale()) { const mark = document.createElement('i'); mark.dataset.lucide = 'check'; mark.setAttribute('aria-hidden', 'true'); button.append(mark); }
    button.addEventListener('click', () => setLocale(item.id as Locale));
    options.append(button);
  });
  details.append(summary, options);
  return details;
}
