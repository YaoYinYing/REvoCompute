import { createIcons, X } from 'lucide';
import { getSystemNotices, type SystemNotices as SystemNoticesPayload } from '../api/app-api';
import { t } from './i18n';

/*
 * Persistent system notices: long-lived operational information (maintenance,
 * service degradation, availability changes, release notes). They are distinct
 * from the transient toast surface, which still owns short action feedback.
 *
 * Notice content is server-owned (`GET /compute/api/system/notices`); nothing
 * here invents a maintenance message. A reader may hide a notice by its stable
 * server identity, and reopen it from the global notice affordance.
 */

const hiddenKey = 'revocompute-notices-hidden';

function hiddenIds(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(hiddenKey) || '[]') as string[]); }
  catch { return new Set(); }
}

function setHidden(ids: Set<string>): void { localStorage.setItem(hiddenKey, JSON.stringify([...ids])); }

const levelLabel: Record<string, string> = { info: 'info', warning: 'warning', critical: 'critical' };

export interface SystemNotices {
  refresh(): Promise<void>;
}

export function mountSystemNotices(options: { button: HTMLButtonElement }): SystemNotices {
  const container = document.createElement('aside');
  container.className = 'sys-notices';
  container.setAttribute('aria-label', t('shell.action.notices'));
  document.body.append(container);

  let notices: SystemNoticesPayload['notices'] = [];
  let loaded = false;
  let expanded = false;

  const render = (): void => {
    const hidden = hiddenIds();
    // Hidden notices leave the page entirely; the global affordance reopens them,
    // which flips ``expanded`` so the reader sees what they previously hid.
    const visible = expanded ? notices : notices.filter(notice => !hidden.has(notice.id));
    container.replaceChildren();
    // The affordance exists only while there is something to read or reopen.
    const restorable = notices.length - visible.length;
    options.button.hidden = !loaded || (visible.length === 0 && restorable === 0);
    const count = visible.length + restorable;
    const badge = options.button.querySelector('.app-notice-count');
    if (badge) badge.textContent = String(count);
    else if (count) {
      const node = document.createElement('span'); node.className = 'app-notice-count'; node.textContent = String(count);
      options.button.append(node);
    }
    visible.forEach(notice => container.append(noticeCard(notice, hidden)));
    if (visible.length) createIcons({ icons: { X }, root: container });
  };

  const noticeCard = (notice: SystemNoticesPayload['notices'][number], hidden: Set<string>): HTMLElement => {
    const card = document.createElement('article'); card.className = 'sys-notice'; card.dataset.tone = notice.level; card.dataset.noticeId = notice.id;
    const header = document.createElement('header');
    const mark = document.createElement('span'); mark.className = 'sys-notice-mark'; mark.setAttribute('aria-hidden', 'true');
    const text = document.createElement('div');
    const title = document.createElement('p'); title.className = 'sys-notice-title'; title.textContent = notice.title;
    const level = document.createElement('span'); level.className = 'sr-only'; level.textContent = levelLabel[notice.level] || notice.level;
    text.append(title, level);
    const body = document.createElement('p'); body.className = 'sys-notice-body'; body.textContent = notice.body;
    text.append(body);
    const tools = document.createElement('div'); tools.className = 'sys-notice-tools';
    if (hidden.has(notice.id)) {
      const restore = document.createElement('button'); restore.type = 'button'; restore.textContent = t('notice.restore');
      restore.addEventListener('click', () => { hidden.delete(notice.id); setHidden(hidden); expanded = true; render(); });
      tools.append(restore);
    }
    const close = document.createElement('button'); close.type = 'button'; close.className = 'icon-button'; close.title = t('notice.hide'); close.setAttribute('aria-label', t('notice.hide'));
    close.innerHTML = '<i data-lucide="x" aria-hidden="true"></i>';
    close.addEventListener('click', () => { hidden.add(notice.id); setHidden(hidden); expanded = false; render(); });
    tools.append(close);
    header.append(mark, text, tools);
    card.append(header);
    return card;
  };

  options.button.addEventListener('click', () => { expanded = !expanded; render(); });

  return {
    async refresh() {
      // The notice surface is global chrome and must never break a page: an
      // unavailable projection simply means there is nothing to announce.
      try { const payload = await getSystemNotices(); notices = payload.notices; }
      catch { notices = []; }
      loaded = true;
      render();
    },
  };
}
