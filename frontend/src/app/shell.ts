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

export function mountShell(root: HTMLElement): AppShell {
  root.replaceChildren();
  applyLocale(locale(), false);

  const shell = document.createElement('div');
  shell.className = 'app-shell';
  shell.dataset.rail = storedRail();

  const brand = document.createElement('a'); brand.className = 'app-brand'; brand.href = '/';
  const logo = document.createElement('img'); logo.src = appAsset('logo.svg'); logo.alt = ''; logo.width = 30; logo.height = 30;
  const brandText = document.createElement('span'); brandText.textContent = 'REvoCompute'; brand.append(logo, brandText);

  const nav = document.createElement('nav'); nav.className = 'app-nav'; nav.setAttribute('aria-label', t('shell.nav.primary'));
  const links: Array<[string, string, string]> = [
    ['/runners', 'workflow', t('shell.nav.runners')], ['/compute/dashboard', 'layout-dashboard', t('shell.nav.dashboard')],
  ];
  links.forEach(([href, icon, label]) => {
    const link = document.createElement('a'); link.href = href; link.title = label; link.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i><span>${label}</span>`;
    const active = location.pathname === href || (href === '/runners' && location.pathname.startsWith('/runners/'));
    if (active) {
      link.setAttribute('aria-current', 'page');
      // Repeated activation of the current item toggles the rail. There is no separate
      // collapse arrow: the control that toggles the rail is the item you are already on.
      link.addEventListener('click', event => { event.preventDefault(); toggleRail(); });
    }
    nav.append(link);
  });

  function toggleRail(): void {
    shell.dataset.rail = shell.dataset.rail === 'expanded' ? 'collapsed' : 'expanded';
    localStorage.setItem(railKey, shell.dataset.rail);
  }

  const header = document.createElement('header'); header.className = 'app-header';
  const actions = document.createElement('div'); actions.className = 'app-header-actions';
  const noticesButton = document.createElement('button'); noticesButton.type = 'button'; noticesButton.className = 'icon-button app-notice-button'; noticesButton.title = t('shell.action.notices'); noticesButton.setAttribute('aria-label', t('shell.action.notices')); noticesButton.innerHTML = '<i data-lucide="bell" aria-hidden="true"></i>';
  noticesButton.hidden = true;
  const adminLinks = document.createElement('details'); adminLinks.className = 'app-admin-links'; adminLinks.hidden = true;
  const adminSummary = document.createElement('summary'); adminSummary.className = 'icon-button'; adminSummary.title = t('shell.action.administration'); adminSummary.setAttribute('aria-label', t('shell.action.administration')); adminSummary.innerHTML = '<i data-lucide="settings" aria-hidden="true"></i>';
  const adminMenu = document.createElement('div'); adminMenu.className = 'app-admin-menu'; adminLinks.append(adminSummary, adminMenu);
  const administrationLinks: Array<[string, string, string]> = [
    ['/compute/user_control', 'users-round', t('shell.admin.users')],
    ['/compute/logs', 'file-text', t('shell.admin.logs')],
    ['/compute/configuration', 'settings', t('shell.admin.configuration')],
  ];
  administrationLinks.forEach(([href, icon, label]) => {
    const link = document.createElement('a'); link.href = href; link.innerHTML = `<i data-lucide="${icon}" aria-hidden="true"></i><span>${label}</span>`;
    if (location.pathname === href) link.setAttribute('aria-current', 'page'); adminMenu.append(link);
  });
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
  actions.append(languageMenu(), noticesButton, adminLinks, userLink, logout, theme);
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
      logout.hidden = !user; adminLinks.hidden = user?.role !== 'admin';
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
