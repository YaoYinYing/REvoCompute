import { createIcons, FileText, LayoutDashboard, LogOut, MoonStar, Plus, Settings, SunMedium, UserRound, UsersRound, Workflow } from 'lucide';
import type { CurrentUser } from '../api/app-api';
import { authorizedJson, clearSessionCredential } from './session';
import { appAsset } from './assets';
import { cycleTheme, storedTheme, type ThemeMode } from './theme';

export interface AppShell { outlet: HTMLElement; notify(message: string, tone?: 'info' | 'success' | 'error'): void; setUser(user: CurrentUser | null): void }

function themeLabel(mode: ThemeMode): string { return `Theme: ${mode[0]!.toUpperCase()}${mode.slice(1)}`; }

export function mountShell(root: HTMLElement): AppShell {
  root.replaceChildren();
  const header = document.createElement('header'); header.className = 'app-header';
  const brand = document.createElement('a'); brand.className = 'app-brand'; brand.href = '/';
  const logo = document.createElement('img'); logo.src = appAsset('logo.svg'); logo.alt = ''; logo.width = 32; logo.height = 32;
  const brandText = document.createElement('span'); brandText.textContent = 'REvoCompute'; brand.append(logo, brandText);
  const nav = document.createElement('nav'); nav.className = 'app-nav'; nav.setAttribute('aria-label', 'Primary');
  const links: Array<[string, string, string]> = [
    ['/runners', 'workflow', 'Runners'], ['/compute/dashboard', 'layout-dashboard', 'Dashboard'],
  ];
  links.forEach(([href, icon, label]) => {
    const link = document.createElement('a'); link.href = href; link.innerHTML = `<i data-lucide="${icon}"></i><span>${label}</span>`;
    if (location.pathname === href || (href === '/runners' && location.pathname.startsWith('/runners/'))) link.setAttribute('aria-current', 'page');
    nav.append(link);
  });
  const actions = document.createElement('div'); actions.className = 'app-header-actions';
  const newTask = document.createElement('a'); newTask.href = '/compute/create_task'; newTask.className = 'app-new-task'; newTask.setAttribute('aria-label', 'New task'); newTask.innerHTML = '<i data-lucide="plus"></i><span>New task</span>';
  if (location.pathname === '/compute/create_task') newTask.setAttribute('aria-current', 'page');
  const adminLinks = document.createElement('details'); adminLinks.className = 'app-admin-links'; adminLinks.hidden = true;
  const adminSummary = document.createElement('summary'); adminSummary.className = 'icon-button'; adminSummary.title = 'Administration'; adminSummary.setAttribute('aria-label', 'Administration'); adminSummary.innerHTML = '<i data-lucide="settings"></i>';
  const adminMenu = document.createElement('div'); adminMenu.className = 'app-admin-menu'; adminLinks.append(adminSummary, adminMenu);
  const administrationLinks: Array<[string, string, string]> = [
    ['/compute/user_control', 'users-round', 'User control'],
    ['/compute/logs', 'file-text', 'Server logs'],
    ['/compute/configuration', 'settings', 'Configuration'],
  ];
  administrationLinks.forEach(([href, icon, label]) => {
    const link = document.createElement('a'); link.href = href; link.innerHTML = `<i data-lucide="${icon}"></i><span>${label}</span>`;
    if (location.pathname === href) link.setAttribute('aria-current', 'page'); adminMenu.append(link);
  });
  const userLink = document.createElement('a'); userLink.href = '/compute/profile'; userLink.className = 'app-user'; userLink.title = 'Profile'; userLink.setAttribute('aria-label', 'Profile'); userLink.innerHTML = '<i data-lucide="user-round"></i><span>Sign in</span>';
  const logout = document.createElement('button'); logout.type = 'button'; logout.className = 'icon-button'; logout.title = 'Log out'; logout.setAttribute('aria-label', 'Log out'); logout.hidden = true; logout.innerHTML = '<i data-lucide="log-out"></i>';
  logout.addEventListener('click', async () => {
    logout.disabled = true;
    try { await authorizedJson('/compute/api/auth/logout', { method: 'POST' }); }
    finally { clearSessionCredential(); location.assign('/compute/login'); }
  });
  const theme = document.createElement('button'); theme.type = 'button'; theme.className = 'icon-button'; theme.title = themeLabel(storedTheme()); theme.setAttribute('aria-label', theme.title); theme.innerHTML = `<i data-lucide="${document.documentElement.dataset.theme === 'dark' ? 'sun-medium' : 'moon-star'}"></i>`;
  theme.addEventListener('click', () => {
    const mode = cycleTheme(); theme.title = themeLabel(mode); theme.setAttribute('aria-label', theme.title);
    theme.innerHTML = `<i data-lucide="${document.documentElement.dataset.theme === 'dark' ? 'sun-medium' : 'moon-star'}"></i>`;
    createIcons({ icons: { MoonStar, SunMedium }, root: theme });
  });
  actions.append(adminLinks, userLink, logout, theme, newTask); header.append(brand, nav, actions);
  const outlet = document.createElement('div'); outlet.className = 'app-outlet'; outlet.id = 'main-content';
  const notices = document.createElement('aside'); notices.className = 'app-notices'; notices.setAttribute('aria-live', 'polite');
  root.append(header, outlet, notices);
  createIcons({ icons: { FileText, LayoutDashboard, LogOut, MoonStar, Plus, Settings, SunMedium, UserRound, UsersRound, Workflow }, root });
  return {
    outlet,
    notify(message, tone = 'info') { const item = document.createElement('div'); item.className = `app-notice notice-${tone}`; item.textContent = message; notices.append(item); setTimeout(() => item.remove(), 4200); },
    setUser(user) { const label = user?.full_name || user?.username || 'Sign in'; userLink.querySelector('span')!.textContent = label; userLink.href = user ? '/compute/profile' : `/compute/login?return_to=${encodeURIComponent(location.pathname)}`; logout.hidden = !user; adminLinks.hidden = user?.role !== 'admin'; },
  };
}
