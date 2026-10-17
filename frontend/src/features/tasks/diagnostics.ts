import { getTaskDiagnostics } from '../../api/app-api';
import { t } from '../../app/i18n';
import './diagnostics.css';

function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag); if (text != null) node.textContent = text; return node;
}

/** One bounded read per opening/retry. Route/dialog disposal aborts pending work. */
export function mountTaskDiagnostics(host: HTMLElement, taskId: string, signal: AbortSignal): void {
  host.classList.add('task-diagnostics'); host.setAttribute('aria-label', t('diagnostics.title'));
  const load = async (): Promise<void> => {
    host.replaceChildren(element('h3', t('diagnostics.title')), element('p', t('diagnostics.loading')));
    host.setAttribute('aria-busy', 'true');
    try {
      const evidence = await getTaskDiagnostics(taskId, signal); if (signal.aborted) return;
      host.replaceChildren(element('h3', t('diagnostics.title')), element('p', evidence.summary));
      const facts = element('dl'); facts.className = 'task-diagnostic-facts';
      const fact = (label: string, value: string): void => { facts.append(element('dt', label), element('dd', value)); };
      fact(t('diagnostics.classification'), evidence.reason_code || t('diagnostics.unknown'));
      fact(t('diagnostics.stage'), evidence.stage || t('diagnostics.unknown'));
      fact(t('diagnostics.exit'), evidence.exit_code == null ? t('diagnostics.unknown') : `${evidence.exit_code} (${evidence.exit_code_source})`);
      if (evidence.scheduler_state) fact(t('diagnostics.scheduler'), evidence.scheduler_state);
      host.append(facts);
      if (evidence.availability === 'expired') host.append(element('p', t('diagnostics.expired')));
      if (!evidence.logs.length) host.append(element('p', t('diagnostics.noLogs')));
      for (const log of evidence.logs) {
        const section = element('section'); const heading = element('h4', t('diagnostics.log', { stream: log.stream }));
        const pre = element('pre', log.preview); pre.tabIndex = 0; pre.setAttribute('aria-label', heading.textContent!);
        const download = element('a', t('diagnostics.download', { stream: log.stream })); download.href = log.download_url; download.download = '';
        section.append(heading, pre);
        if (log.truncated) section.append(element('p', t('diagnostics.truncated')));
        section.append(download); host.append(section);
      }
      host.append(element('p', t('diagnostics.context')));
    } catch (error) {
      if (signal.aborted || (error as Error).name === 'AbortError') return;
      const retry = element('button', t('diagnostics.retry')); retry.type = 'button'; retry.addEventListener('click', () => void load(), { once: true });
      host.replaceChildren(element('h3', t('diagnostics.title')), element('p', t('diagnostics.loadFailed')), retry);
    } finally { if (!signal.aborted) host.setAttribute('aria-busy', 'false'); }
  };
  void load();
}
