import { Bell, Check, createIcons, FileText, Languages, LayoutDashboard, LogOut, MoonStar, Plus, Settings, SunMedium, UserRound, UsersRound, Workflow } from 'lucide';
import type { CurrentUser } from '../api/app-api';
import { authorizedJson, clearSessionCredential } from './session';
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
const shellIcons = { Bell, Check, FileText, Languages, LayoutDashboard, LogOut, MoonStar, Plus, Settings, SunMedium, UserRound, UsersRound, Workflow };

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
    ['admin', [
      ['/compute/user_control', 'users-round', t('shell.admin.users')],
      ['/compute/logs', 'file-text', t('shell.admin.logs')],
      ['/compute/configuration', 'settings', t('shell.admin.configuration')],
    ]],
  ];
  for (const [region, links] of destinations) {
    for (const [href, icon, label] of links) groups[region].items.append(navLink(href, icon, label));
  }
  Object.values(groups).forEach(group => nav.append(group.element));
  // The Account region restates the current user's identity, so it follows the same
  // session state as the top-bar profile affordance — one identity, two reach points.
  const accountLink = groups.account.items.firstElementChild as HTMLAnchorElement;
  accountLink.title = t('shell.action.profile');
  accountLink.setAttribute('aria-label', t('shell.action.profile'));
  // The group label is a visible heading on the desktop rail. On the mobile bar
  // the links are laid out directly on the bar, so the headings there are removed
  // from the accessibility tree rather than labelling a region that is not grouped.
  const syncGroupHeadings = (grouped: boolean): void => {
    Object.values(groups).forEach(group => group.heading.hidden = !grouped);
  };
  syncGroupHeadings(navGrouped.matches);
  navGrouped.addEventListener('change', event => syncGroupHeadings(event.matches));

  function navGroup(region: string, labelKey: string): { element: HTMLElement; heading: HTMLElement; items: HTMLElement } {
    const element = document.createElement('div'); element.className = 'app-nav-group'; element.dataset.navGroup = region;
    // The group name labels the region on the desktop rail. On the mobile bottom
    // bar it cannot label a column of links, so it is removed there (see below).
    const heading = document.createElement('h2'); heading.className = 'app-nav-group-label'; heading.textContent = t(labelKey);
    const items = document.createElement('div'); items.className = 'app-nav-group-items';
    element.append(heading, items);
    return { element, heading, items };
  }

  function navLink(href: string, icon: string, label: string): HTMLElement {
    const link = document.createElement('a'); link.href = href; link.title = label; link.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i><span>${label}</span>`;
    if (currentDestination(href)) {
      link.setAttribute('aria-current', 'page');
      // Repeated activation of the current item toggles the desktop rail. There is
      // no separate collapse arrow: the control that toggles the rail is the item
      // you are already on. On the mobile bar there is no rail to toggle, so the
      // item navigates like any other.
      link.addEventListener('click', event => {
        if (!desktopRail.matches) return;
        event.preventDefault();
        toggleRail();
      });
    }
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
  const userLink = document.createElement('a'); userLink.href = '/compute/profile'; userLink.className = 'app-user'; userLink.title = t('shell.action.profile'); userLink.setAttribute('aria-label', t('shell.action.profile')); userLink.innerHTML = `<i data-lucide="user-round" aria-hidden="true"></i><span>${t('shell.action.signIn')}</span>`;
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
  const notices = document.createElement('aside'); notices.className = 'app-notices'; notices.setAttribute('aria-live', 'polite');
  shell.append(brand, header, nav, outlet, notices);
  root.append(shell);
  createIcons({ icons: shellIcons, root: shell });

  const systemNotices = mountSystemNotices({ button: noticesButton });

  return {
    outlet,
    notify(message, tone = 'info') { const item = document.createElement('div'); item.className = `app-notice notice-${tone}`; item.textContent = message; notices.append(item); setTimeout(() => item.remove(), 4200); },
    setUser(user) {
      const label = user?.full_name || user?.username || t('shell.action.signIn');
      userLink.querySelector('span')!.textContent = label;
      userLink.href = user ? '/compute/profile' : `/compute/login?return_to=${encodeURIComponent(location.pathname)}`;
      logout.hidden = !user;
      // The Account destination follows the same session state as the top-bar
      // profile affordance: a signed-out visitor is offered the sign-in route.
      accountLink.href = user ? '/compute/profile' : `/compute/login?return_to=${encodeURIComponent(location.pathname)}`;
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
