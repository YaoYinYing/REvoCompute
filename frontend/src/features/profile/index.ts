import { createIcons } from 'lucide';
import type { CurrentUser } from '../../api/app-api';
import type { AccountSection } from '../../app/router';
import { accountNavigation, type AppShell } from '../../app/shell';
import { accountIcons, accountPanelFor, errorMessage } from './sections';
import './account.css';

/**
 * The user's own Account, one page per section.
 *
 * The shell and local index share one destination vocabulary: the sections are
 * direct destinations in the personal workspace, and each one is its own
 * route with its own document title. The page owns its single `h1`; the shell
 * owns the `main` landmark it mounts into. A section that cannot load reports the
 * failure in place rather than replacing the shell.
 */
export async function mountAccount(root: HTMLElement, shell: AppShell, user: CurrentUser, section: AccountSection): Promise<void> {
  const page = document.createElement('main');
  page.className = 'account-page';
  page.append(accountPanelFor(section, shell, user));
  const layout = document.createElement('div'); layout.className = 'account-layout';
  layout.append(accountNavigation(), page); root.replaceChildren(layout);
  const heading = page.querySelector('h1');
  document.title = `${heading?.textContent || 'Account'} | REvoCompute`;
  createIcons({ icons: accountIcons, root: page });
  try { await preloadAccountPanel(page, section); }
  catch (error) { shell.notify(errorMessage(error, 'This account section could not be loaded.'), 'error'); }
}

/** Await the section's own resource load so the route is ready when it settles. */
async function preloadAccountPanel(page: HTMLElement, section: AccountSection): Promise<void> {
  if (section === 'api-key') await waitFor(page, '[data-generate-key]:not([hidden]), [data-revoke-key]:not([hidden]), [data-api-key-message]');
  else if (section === 'runner-access') await waitFor(page, '[data-access-list] > *');
  else if (section === 'gpu-credits') await waitFor(page, '[data-gpu-credit] > *');
  else if (section === 'metrics') await waitFor(page, '[data-metrics] > *');
}

/** Resolve once a selector matches in the freshly-mounted panel, or when it is gone. */
function waitFor(page: HTMLElement, selector: string): Promise<void> {
  if (page.querySelector(selector)) return Promise.resolve();
  return new Promise(resolve => {
    let settled = false;
    const done = (): void => { if (settled) return; settled = true; observer.disconnect(); resolve(); };
    const observer = new MutationObserver(() => { if (page.querySelector(selector)) done(); });
    observer.observe(page, { childList: true, subtree: true });
    window.setTimeout(done, 2500);
  });
}
