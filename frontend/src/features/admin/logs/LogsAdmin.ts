import type { AppShell } from '../../../app/shell';
import { adminApi } from '../api';
import { button, element, empty, formatBytes, formatDate, setBusy, text } from '../shared/dom';

const logSources: Array<[string, string]> = [
  ['gunicorn-access', 'Gunicorn access'], ['gunicorn-error', 'Gunicorn error'], ['celery-worker', 'Celery worker'],
  ['operational-events', 'Operational events'], ['maintenance', 'Maintenance'],
];
const maxRenderedCharacters = 1_000_000;
const maxRenderedLines = 5_000;

export function boundLogText(raw: string): { text: string; truncated: boolean } {
  let textValue = raw;
  let truncated = false;
  if (textValue.length > maxRenderedCharacters) { textValue = textValue.slice(-maxRenderedCharacters); truncated = true; }
  const lines = textValue.split('\n');
  if (lines.length > maxRenderedLines) { textValue = lines.slice(-maxRenderedLines).join('\n'); truncated = true; }
  return { text: textValue, truncated };
}

export class LogsAdmin {
  private selected = logSources[0]![0];
  private output = element('pre', 'admin-log-output');
  private status = text('p', '', 'admin-log-status');
  private controller: AbortController | null = null;
  private sourceButtons = new Map<string, HTMLButtonElement>();

  constructor(private readonly shell: AppShell) {}

  async mount(root: HTMLElement): Promise<void> {
    const toolbar = element('div', 'log-toolbar');
    const sourceTabs = element('div', 'log-source-tabs');
    sourceTabs.setAttribute('role', 'tablist'); sourceTabs.setAttribute('aria-label', 'Server log source');
    this.output.id = 'active-server-log';
    for (const [id, label] of logSources) {
      const control = button(label);
      control.id = `log-source-${id}`;
      control.setAttribute('role', 'tab'); control.setAttribute('aria-selected', String(id === this.selected));
      control.setAttribute('aria-controls', this.output.id);
      control.tabIndex = id === this.selected ? 0 : -1;
      control.addEventListener('click', () => { this.selected = id; this.updateSourceSelection(); void this.loadLog(); });
      this.sourceButtons.set(id, control); sourceTabs.append(control);
    }
    const sourceIds = logSources.map(([id]) => id);
    this.sourceButtons.forEach((control, id) => control.addEventListener('keydown', event => {
      const index = sourceIds.indexOf(id); const offsets: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1 };
      let target = index;
      if (event.key === 'Home') target = 0;
      else if (event.key === 'End') target = sourceIds.length - 1;
      else if (event.key in offsets) target = (index + offsets[event.key]! + sourceIds.length) % sourceIds.length;
      else return;
      event.preventDefault(); this.selected = sourceIds[target]!; this.updateSourceSelection();
      this.sourceButtons.get(this.selected)?.focus(); void this.loadLog();
    }));
    const refresh = button('Refresh'); refresh.addEventListener('click', () => void this.loadLog(refresh)); toolbar.append(sourceTabs, refresh);
    this.output.tabIndex = 0; this.output.setAttribute('role', 'tabpanel');
    this.updateSourceSelection();
    const active = element('section', 'admin-section', [toolbar, this.status, this.output]);

    const archiveRoot = element('div', 'archive-list');
    const archiveStatus = text('p', 'Open to load managed log archives.', 'admin-log-status');
    const refreshArchives = button('Refresh archives'); refreshArchives.addEventListener('click', () => void this.loadArchives(archiveRoot, archiveStatus, refreshArchives));
    const details = element('details', 'admin-section archive-panel');
    details.append(element('summary', '', [text('strong', 'Rotated log archives')]), element('div', 'admin-section-heading', [archiveStatus, refreshArchives]), archiveRoot);
    let loaded = false;
    details.addEventListener('toggle', () => { if (details.open && !loaded) { loaded = true; void this.loadArchives(archiveRoot, archiveStatus, refreshArchives); } });
    root.append(active, details);
    await this.loadLog();
  }

  private updateSourceSelection(): void {
    this.sourceButtons.forEach((control, id) => {
      const selected = id === this.selected;
      control.setAttribute('aria-selected', String(selected)); control.tabIndex = selected ? 0 : -1; control.classList.toggle('is-selected', selected);
      if (selected) this.output.setAttribute('aria-labelledby', control.id);
    });
  }

  private async loadLog(control?: HTMLButtonElement): Promise<void> {
    this.controller?.abort(); this.controller = new AbortController();
    this.output.textContent = ''; this.status.textContent = `Loading ${this.selected}...`;
    if (control) setBusy(control, true, 'Loading...');
    try {
      const fetched = await adminApi.getLog(this.selected, this.controller.signal, maxRenderedCharacters);
      const bounded = boundLogText(fetched.text); this.output.textContent = bounded.text;
      this.output.scrollTop = this.output.scrollHeight;
      this.status.textContent = `Loaded ${this.selected}: ${formatBytes(new Blob([bounded.text]).size)} rendered${fetched.truncated || bounded.truncated ? ', showing the latest 5,000 lines up to 1 MB' : ''}.`;
    } catch (error) {
      if ((error as Error).name !== 'AbortError') { this.status.textContent = (error as Error).message || 'Unable to load this log.'; this.shell.notify(this.status.textContent, 'error'); }
    } finally { if (control) setBusy(control, false); }
  }

  private async loadArchives(root: HTMLElement, status: HTMLElement, control: HTMLButtonElement): Promise<void> {
    setBusy(control, true, 'Loading...'); status.textContent = 'Loading managed archives...'; root.replaceChildren();
    try {
      const groups = await adminApi.listLogArchives();
      groups.forEach(group => {
        const branch = element('details', 'archive-group');
        branch.append(element('summary', '', [text('strong', group.filename), text('span', `${group.archives.length} archive(s)`) ]));
        const list = element('ul');
        if (!group.archives.length) list.append(element('li', '', ['No rotated files.']));
        group.archives.forEach(archive => {
          const link = element('a'); link.href = adminApi.archiveUrl(archive.filename); link.download = archive.filename; link.textContent = archive.filename;
          list.append(element('li', '', [link, text('span', `${formatBytes(archive.size)}, ${formatDate(archive.modified_at)}`)]));
        });
        branch.append(list); root.append(branch);
      });
      if (!groups.length) root.append(empty('No log archive groups are available.'));
      status.textContent = 'Managed archives loaded.';
    } catch (error) { root.replaceChildren(empty((error as Error).message || 'Unable to load log archives.', true)); status.textContent = 'Archive loading failed.'; }
    finally { setBusy(control, false); }
  }
}
