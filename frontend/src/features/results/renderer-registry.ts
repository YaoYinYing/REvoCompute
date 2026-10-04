import { resultFileName, type ResultArtifact, type ResultFile, type PreviewCapability, type ResultView } from '../../api/result-types';

export interface RendererContext {
  signal: AbortSignal;
  taskId: string;
}

export interface ArtifactRenderer {
  id: string;
  render(artifact: ResultFile, host: HTMLElement, context: RendererContext): Promise<void | { destroy(): void }>;
}

/**
 * A server-declared result view's renderer, keyed by its declared `plugin`.
 *
 * A view renderer receives the view's own manifest definition and the first
 * resolved source artifact; it never branches on a task or runner name.
 */
export interface ViewRenderer {
  id: string;
  render(
    view: ResultView,
    artifact: ResultFile | null,
    host: HTMLElement,
    context: RendererContext,
  ): Promise<void | { destroy(): void }>;
}

export class ViewRendererRegistry {
  private readonly renderers = new Map<string, ViewRenderer>();

  register(renderer: ViewRenderer): this {
    if (this.renderers.has(renderer.id)) throw new Error(`Duplicate view renderer: ${renderer.id}`);
    this.renderers.set(renderer.id, renderer);
    return this;
  }

  resolve(view: ResultView): ViewRenderer | null {
    return this.renderers.get(view.plugin) || null;
  }
}

const STRUCTURES = new Set(['chemical/x-pdb', 'chemical/x-cif', 'chemical/x-mmcif']);
const PREVIEWS = new Set<PreviewCapability>(['structure', 'molecular_structure', 'table', 'plot', 'image', 'text', 'archive', 'download_only']);

export function artifactCapability(artifact: ResultFile): PreviewCapability {
  const declared = artifact.capability !== 'unknown' ? artifact.capability : artifact.preview;
  if (declared && PREVIEWS.has(declared as PreviewCapability)) return declared as PreviewCapability;
  const name = resultFileName(artifact);
  if (STRUCTURES.has(artifact.media_type || '') || /\.(?:pdb|cif|mmcif)$/i.test(name)) return 'structure';
  if ((artifact.media_type || '').startsWith('image/') || /\.(?:png|jpe?g|webp|gif)$/i.test(name)) return 'image';
  if (/\.(?:csv|tsv|xlsx?)$/i.test(name)) return 'table';
  if ((artifact.media_type || '').startsWith('text/') || /\.(?:txt|log|json|ya?ml|a3m|fasta?)$/i.test(name)) return 'text';
  return 'download_only';
}

export class RendererRegistry {
  private readonly renderers = new Map<string, ArtifactRenderer>();

  register(renderer: ArtifactRenderer): this {
    if (this.renderers.has(renderer.id)) throw new Error(`Duplicate artifact renderer: ${renderer.id}`);
    this.renderers.set(renderer.id, renderer);
    return this;
  }

  resolve(artifact: ResultFile): ArtifactRenderer | null {
    const capability = artifactCapability(artifact);
    return this.renderers.get(capability) ||
      (capability === 'molecular_structure' ? this.renderers.get('structure') : null) || null;
  }
}

export function createBasicRenderers(): ArtifactRenderer[] {
  return [
    {
      id: 'image',
      async render(artifact, host) {
        const image = document.createElement('img');
        image.className = 'result-image'; image.alt = resultFileName(artifact); image.src = artifact.url;
        host.replaceChildren(image);
      },
    },
    {
      id: 'text',
      async render(artifact, host, context) {
        if (artifact.size > 262_144) throw new Error('This text is too large to preview. Download it instead.');
        const response = await fetch(artifact.url, {
          credentials: 'same-origin', signal: context.signal, headers: { Range: 'bytes=0-262143' },
        });
        if (!response.ok && response.status !== 206) throw new Error('Text preview could not be loaded.');
        const pre = document.createElement('pre'); pre.textContent = await response.text(); host.replaceChildren(pre);
      },
    },
    {
      id: 'table',
      async render(artifact, host, context) {
        const name = resultFileName(artifact), encoded = name.split('/').map(encodeURIComponent).join('/');
        const url = artifact.table_url || ('path' in artifact
          ? `/compute/api/results/${encodeURIComponent(context.taskId)}/tables/${encoded}?limit=100`
          : null);
        if (!url) throw new Error('This table has no authorized preview URL.');
        const response = await fetch(url, { credentials: 'same-origin', signal: context.signal });
        if (!response.ok) throw new Error('Table preview could not be loaded.');
        const page = await response.json() as { columns: unknown[]; rows: unknown[][]; has_more?: boolean };
        const table = document.createElement('table'); table.className = 'result-table';
        const head = document.createElement('thead'); const heading = document.createElement('tr');
        page.columns.forEach((column) => { const cell = document.createElement('th'); cell.scope = 'col'; cell.textContent = String(column); heading.append(cell); });
        head.append(heading); const body = document.createElement('tbody');
        page.rows.forEach((row) => { const line = document.createElement('tr'); row.forEach((value) => { const cell = document.createElement('td'); cell.textContent = String(value ?? ''); line.append(cell); }); body.append(line); });
        table.append(head, body); host.replaceChildren(table);
        if (page.has_more) { const note = document.createElement('p'); note.className = 'result-note'; note.textContent = 'Showing the first 100 rows.'; host.append(note); }
      },
    },
    {
      id: 'download_only',
      async render(_artifact, host) {
        const message = document.createElement('p'); message.className = 'result-empty';
        message.textContent = 'No inline preview is available. The file remains available to download.'; host.replaceChildren(message);
      },
    },
  ];
}
