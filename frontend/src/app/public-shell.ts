import { createIcons, LogIn, Menu, MoonStar, SunMedium, UserRound } from 'lucide';
import type { CurrentUser } from '../api/app-api';
import type { AppShell } from './shell';
import { cycleTheme, storedTheme, type ThemeMode } from './theme';

function themeLabel(mode: ThemeMode): string { return `Theme: ${mode[0]!.toUpperCase()}${mode.slice(1)}`; }

export function mountPublicShell(root: HTMLElement): AppShell {
  root.replaceChildren();
  const header = document.createElement('header');
  header.className = 'public-header';
  header.innerHTML = `
    <a class="public-brand" href="/" aria-label="REvoDesign home"><img src="/compute/logo.svg" alt="" width="36" height="36"><span>REvoDesign</span></a>
    <details class="public-navigation">
      <summary class="icon-button" aria-label="Open navigation"><i data-lucide="menu"></i></summary>
      <nav aria-label="Public navigation">
        <a href="/">Home</a><a href="/runners">Runners</a><a href="/api-docs">API</a><a href="/skills.md">Agent API</a>
        <a href="https://yaoyinying.github.io/REvoCompute/">Documentation</a>
        <a href="https://github.com/YaoYinYing/REvoCompute" rel="noopener noreferrer">GitHub</a>
      </nav>
    </details>`;
  const actions = document.createElement('div');
  actions.className = 'public-actions';
  const account = document.createElement('a');
  account.className = 'public-account secondary-button';
  account.href = '/compute/login';
  account.innerHTML = '<i data-lucide="log-in"></i><span>Sign in</span>';
  const theme = document.createElement('button');
  theme.type = 'button';
  theme.className = 'icon-button';
  theme.title = themeLabel(storedTheme());
  theme.setAttribute('aria-label', theme.title);
  theme.innerHTML = `<i data-lucide="${document.documentElement.dataset.theme === 'dark' ? 'sun-medium' : 'moon-star'}"></i>`;
  theme.addEventListener('click', () => {
    const mode = cycleTheme();
    theme.title = themeLabel(mode);
    theme.setAttribute('aria-label', theme.title);
    theme.innerHTML = `<i data-lucide="${document.documentElement.dataset.theme === 'dark' ? 'sun-medium' : 'moon-star'}"></i>`;
    createIcons({ icons: { MoonStar, SunMedium }, root: theme });
  });
  actions.append(account, theme);
  header.append(actions);
  const navigation = header.querySelector<HTMLDetailsElement>('.public-navigation')!;
  const desktopNavigation = matchMedia('(min-width: 66.01rem)');
  const syncNavigation = (desktop: boolean): void => {
    if (desktop) navigation.open = true;
    else if (!navigation.matches(':focus-within')) navigation.open = false;
  };
  syncNavigation(desktopNavigation.matches);
  desktopNavigation.addEventListener('change', event => syncNavigation(event.matches));
  const outlet = document.createElement('div');
  outlet.className = 'public-outlet';
  outlet.id = 'main-content';
  const notices = document.createElement('aside');
  notices.className = 'app-notices';
  notices.setAttribute('aria-live', 'polite');
  root.append(header, outlet, notices);
  createIcons({ icons: { LogIn, Menu, MoonStar, SunMedium, UserRound }, root: header });
  return {
    outlet,
    notify(message, tone = 'info') {
      const item = document.createElement('div');
      item.className = `app-notice notice-${tone}`;
      item.textContent = message;
      notices.append(item);
      setTimeout(() => item.remove(), 4200);
    },
    setUser(user: CurrentUser | null) {
      account.href = user ? '/compute/profile' : '/compute/login';
      account.innerHTML = `<i data-lucide="${user ? 'user-round' : 'log-in'}"></i><span>${user ? 'Profile' : 'Sign in'}</span>`;
      createIcons({ icons: { LogIn, UserRound }, root: account });
    },
  };
}
