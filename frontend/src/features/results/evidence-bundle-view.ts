/*
 * `evidence-bundle` ResultView rendering: every declared item as one bounded entry, with an
 * inline image for an image capability and a download link for everything else.
 *
 * The bundle carries raw artifacts by path, so this renderer states each item's published
 * type and size; it never inspects bytes to decide what they mean.
 */
import { resultFileName, type ResultFile, type ResultView } from '../../api/result-types';
import { t } from '../../app/i18n';
import { localName } from './artifact-tree';
import { artifactCapability } from './renderer-registry';
import type { ResolvedViewSources, ViewRenderer } from './renderer-registry';

export interface EvidenceItem {
  file: ResultFile;
  source: string;
  capability: string;
}

/** Every declared item in declared source order, tagged with the source that selected it. */
export function bundleItems(sources: ResolvedViewSources): EvidenceItem[] {
  return Object.entries(sources).flatMap(([source, files]) => files.map((file) => ({
    file, source, capability: artifactCapability(file),
  })));
}

function formatBytes(value = 0): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 ** 2).toFixed(2)} MiB`;
}

/** Render a declared `evidence-bundle` view as its published items. */
export function createEvidenceBundleViewRenderer(): ViewRenderer {
  return {
    id: 'evidence-bundle',
    async render(view: ResultView, sources: ResolvedViewSources, host: HTMLElement) {
      const items = bundleItems(sources);
      const section = document.createElement('section'); section.className = 'evidence-bundle-view';
      const heading = document.createElement('h3'); heading.textContent = view.title;
      section.append(heading);
      if (!items.length) {
        const empty = document.createElement('p'); empty.className = 'result-empty';
        empty.textContent = t('results.evidenceBundle.empty');
        section.append(empty);
      }
      const list = document.createElement('ul'); list.className = 'evidence-bundle-items';
      items.forEach((item) => {
        const name = resultFileName(item.file);
        const row = document.createElement('li'); row.className = 'evidence-bundle-item';
        row.dataset.source = item.source; row.dataset.capability = item.capability; row.dataset.path = name;
        const title = document.createElement('strong'); title.textContent = localName(name);
        const meta = document.createElement('span'); meta.className = 'result-note';
        meta.textContent = `${item.capability} · ${formatBytes(item.file.size)}`;
        const link = document.createElement('a'); link.className = 'result-button result-button-small';
        link.href = item.file.url; link.setAttribute('download', ''); link.textContent = t('results.evidenceBundle.download');
        link.dataset.download = name;
        row.append(title, meta, link);
        if (item.capability === 'image') {
          const image = document.createElement('img'); image.className = 'result-image';
          image.loading = 'lazy'; image.alt = localName(name); image.src = item.file.url;
          image.addEventListener('error', () => { image.replaceWith(Object.assign(document.createElement('p'), {
            className: 'result-note', textContent: t('results.evidenceBundle.imageFailed', { name: localName(name) }),
          })); }, { once: true });
          row.append(image);
        }
        list.append(row);
      });
      section.append(list); host.replaceChildren(section);
      return { destroy: () => section.replaceChildren() };
    },
  };
}
