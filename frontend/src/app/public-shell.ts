import { Check, createIcons, Languages, LogIn, Menu, MoonStar, SunMedium, UserRound } from 'lucide';
import type { CurrentUser } from '../api/app-api';
import type { AppShell } from './shell';
import { appAsset } from './assets';
import { locale, locales, setLocale, t, type Locale } from './i18n';
import { cycleTheme, storedTheme, type ThemeMode } from './theme';

const publicIcons = { Check, Languages, LogIn, Menu, MoonStar, SunMedium, UserRound };

function themeLabel(mode: ThemeMode): string { return `${t('shell.action.theme')}: ${t(`theme.${mode}`)}`; }

export function mountPublicShell(root: HTMLElement): AppShell {
  root.replaceChildren();
  const header = document.createElement('header');
  header.className = 'public-header';
  header.innerHTML = `
    <a class="public-brand" href="/" aria-label="${t('public.home')}"><img src="${appAsset('logo.svg')}" alt="" width="36" height="36"><span>${t('public.brand')}</span></a>
    <details class="public-navigation">
      <summary class="icon-button" aria-label="${t('public.nav.open')}"><i data-lucide="menu" aria-hidden="true"></i></summary>
      <nav aria-label="${t('public.nav.label')}">
        <a href="/">${t('public.nav.home')}</a><a href="/runners">${t('public.nav.runners')}</a><a href="/api-docs">${t('public.nav.api')}</a><a href="/skills.md">${t('public.nav.agentApi')}</a>
        <a href="https://yaoyinying.github.io/REvoCompute/">${t('public.nav.documentation')}</a>
        <a href="https://github.com/YaoYinYing/REvoCompute" rel="noopener noreferrer">${t('public.nav.github')}</a>
      </nav>
    </details>`;
  const actions = document.createElement('div');
  actions.className = 'public-actions';
  const account = document.createElement('a');
  account.className = 'public-account secondary-button';
  account.href = '/compute/login';
  account.title = t('shell.action.signIn');
  account.setAttribute('aria-label', account.title);
  account.innerHTML = `<i data-lucide="log-in" aria-hidden="true"></i><span>${t('shell.action.signIn')}</span>`;
  const theme = document.createElement('button');
  theme.type = 'button';
  theme.className = 'icon-button';
  theme.title = themeLabel(storedTheme());
  theme.setAttribute('aria-label', theme.title);
  theme.innerHTML = `<i data-lucide="${document.documentElement.dataset.theme === 'dark' ? 'sun-medium' : 'moon-star'}" aria-hidden="true"></i>`;
  theme.addEventListener('click', () => {
    const mode = cycleTheme();
    theme.title = themeLabel(mode);
    theme.setAttribute('aria-label', theme.title);
    theme.innerHTML = `<i data-lucide="${document.documentElement.dataset.theme === 'dark' ? 'sun-medium' : 'moon-star'}" aria-hidden="true"></i>`;
    createIcons({ icons: { MoonStar, SunMedium }, root: theme });
  });
  actions.append(languageMenu(), account, theme);
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
  const feedback = document.createElement('div'); feedback.className = 'app-feedback';
  feedback.append(notices);
  root.append(header, outlet, feedback);
  createIcons({ icons: publicIcons, root: header });
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
      account.title = t(user ? 'shell.action.profile' : 'shell.action.signIn');
      account.setAttribute('aria-label', account.title);
      account.innerHTML = `<i data-lucide="${user ? 'user-round' : 'log-in'}" aria-hidden="true"></i><span>${t(user ? 'shell.action.profile' : 'shell.action.signIn')}</span>`;
      createIcons({ icons: { LogIn, UserRound }, root: account });
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
