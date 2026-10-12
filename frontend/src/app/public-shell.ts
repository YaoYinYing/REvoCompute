import { createIcons, LogIn, Menu, UserRound } from 'lucide';
import type { CurrentUser } from '../api/app-api';
import type { AppShell } from './shell';
import { appAsset } from './assets';
import { t } from './i18n';
import { languageMenu, themeButton } from './localize';

const publicIcons = { LogIn, Menu, UserRound };

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
  actions.append(languageMenu(), account, themeButton());
  header.append(actions);
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
    // The public header carries one account affordance and no navigation state to
    // synchronize; the methods exist so the shared router can address either shell
    // without knowing which one it mounted.
    syncActive() {},
    refreshNotices() {},
  };
}
