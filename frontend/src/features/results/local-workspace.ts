import { t } from '../../app/i18n';
import { openLocalResult, type LocalResultSource } from './local-source';
import { ResultWorkspace } from './ResultWorkspace';

/**
 * The Local Result Workspace's own page, before a folder is open.
 *
 * The page is a door with one action: choose the folder. What it then shows is the ordinary
 * Result Workspace reading that folder — one workspace, two sources — rather than a second
 * results application with its own renderers.
 */
export interface LocalWorkspace {
  destroy(): void;
}

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

export function mountLocalResultWorkspace(root: HTMLElement): LocalWorkspace {
  let source: LocalResultSource | null = null;
  let workspace: ResultWorkspace | null = null;
  let disposed = false;

  const page = element('main', 'result-app local-result-open');
  const header = element('header', 'result-header');
  const identity = element('div', 'result-identity');
  const title = element('h1', '', t('results.local.title'));
  const intro = element('p', 'result-meta', t('results.local.intro'));
  identity.append(title, intro);
  header.append(identity);

  const gate = element('section', 'result-status');
  gate.setAttribute('aria-live', 'polite');
  const picker = element('input') as HTMLInputElement;
  picker.type = 'file';
  // `webkitdirectory` is the portable directory chooser: every browser this application
  // supports hands back the files with their relative paths, and no permission persists
  // past the reader's own selection.
  picker.setAttribute('webkitdirectory', '');
  picker.setAttribute('directory', '');
  picker.multiple = true;
  picker.hidden = true;
  const open = element('button', 'result-button', t('results.local.open')) as HTMLButtonElement;
  open.type = 'button';
  open.addEventListener('click', () => picker.click());
  const report = element('p', 'result-note');
  report.setAttribute('role', 'status');
  const mount = element('div', 'local-result-mount');
  page.append(header, gate, open, picker, report, mount);
  root.replaceChildren(page);

  const close = (): void => {
    workspace?.destroy(); workspace = null;
    source?.close(); source = null;
    mount.replaceChildren();
  };

  picker.addEventListener('change', () => {
    void (async () => {
      const files = [...(picker.files || [])];
      // The same folder can be chosen again after it failed: the input is cleared so the
      // second choice is a new change event rather than a silent no-op.
      picker.value = '';
      if (!files.length) return;
      report.textContent = t('results.local.reading');
      report.dataset.error = 'false';
      open.disabled = true;
      try {
        const label = files.find((file) => (file as File & { webkitRelativePath?: string }).webkitRelativePath)
          ?.webkitRelativePath?.split('/')[0] || t('results.local.folder');
        const opened = await openLocalResult({ files, label });
        if (disposed) { opened.close(); return; }
        close();
        source = opened;
        workspace = new ResultWorkspace(mount, async (host, options) => {
          const { MolecularViewer } = await import('../structure/MolecularViewer');
          return MolecularViewer.mount(host, options);
        }, opened);
        // One offer per page: the workspace already stated the folder's verification, so the
        // door's own report yields to what the result itself says.
        report.textContent = '';
        await workspace.load();
      } catch (error) {
        if (disposed) return;
        report.textContent = (error as Error).message || t('results.local.failed');
        report.dataset.error = 'true';
      } finally { open.disabled = false; }
    })();
  });

  // A local result's files are the reader's own; offering them back as a download of the
  // opened folder is not a promise this page makes, and no artifact carries a Server URL.
  const releases = new AbortController();
  window.addEventListener('pagehide', close, { signal: releases.signal });

  return {
    destroy(): void {
      if (disposed) return;
      disposed = true;
      releases.abort();
      close();
      root.replaceChildren();
    },
  };
}
