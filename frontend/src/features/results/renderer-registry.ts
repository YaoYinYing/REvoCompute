import { resultFileName, type ResultArtifact, type ResultFile, type PreviewCapability, type ResultView } from '../../api/result-types';
import { t } from '../../app/i18n';

export interface RendererContext {
  signal: AbortSignal;
  taskId: string;
  // Mount one structure artifact into `host` through the workspace's own molecular
  // stage; absent for an embedder that has none. A view renderer that shows a
  // candidate as a structure uses this instead of carrying a second viewer.
  openStructure?(artifact: ResultFile, host: HTMLElement): Promise<void>;
  // Invalidate the shared molecular stage; a view renderer calls this when the
  // structure it opened is superseded by a selection that is not a structure.
  closeStructure?(): void;
  // Apply the molecular selection a rendered row declares, in the workspace's own
  // structure vocabulary; absent for an embedder without a molecular stage.
  selectStructure?(selection: { chain: string; residue: number; numbering?: string }): void;
}

export interface ArtifactRenderer {
  id: string;
  render(artifact: ResultFile, host: HTMLElement, context: RendererContext): Promise<void | { destroy(): void }>;
}

/**
 * Every declared source of one view, resolved to the manifest artifacts that
 * satisfy it, keyed by the source name the Server declared (``topology``,
 * ``coordinates``, ``matrices``, ...). Source names and their resolved order
 * are preserved end to end; a missing source resolves to an empty list rather
 * than being dropped, so a renderer can state which source is absent.
 */
export type ResolvedViewSources = Record<string, ResultFile[]>;

/** The first published artifact across a view's sources, in declared order. */
export function firstViewSource(sources: ResolvedViewSources): ResultFile | null {
  for (const artifacts of Object.values(sources)) {
    if (artifacts.length) return artifacts[0]!;
  }
  return null;
}

/**
 * A server-declared result view's renderer, keyed by its declared `plugin`.
 *
 * A view renderer receives the view's own manifest definition and every source
 * it declares, each resolved to artifacts; it never branches on a task or
 * runner name.
 */
export interface ViewRenderer {
  id: string;
  render(
    view: ResultView,
    sources: ResolvedViewSources,
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
// A gzipped structure keeps the underlying format's media type (the server
// guesses `chemical/x-cif` from `*.cif.gz`), so the media type alone already
// routes one to the structure renderer. The name test has to allow the
// compression suffix too, because an artifact served without a media type must
// still preview rather than fall through to download-only.
const STRUCTURE_NAME = /\.(?:pdb|cif|mmcif)(?:\.gz)?$/i;
const PREVIEWS = new Set<PreviewCapability>(['structure', 'molecular_structure', 'table', 'plot', 'image', 'text', 'archive', 'download_only']);

export function artifactCapability(artifact: ResultFile): PreviewCapability {
  const declared = artifact.capability !== 'unknown' ? artifact.capability : artifact.preview;
  if (declared && PREVIEWS.has(declared as PreviewCapability)) return declared as PreviewCapability;
  const name = resultFileName(artifact);
  if (STRUCTURES.has(artifact.media_type || '') || STRUCTURE_NAME.test(name)) return 'structure';
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
        if (artifact.size > 262_144) throw new Error(t('results.textTooLarge'));
        const response = await fetch(artifact.url, {
          credentials: 'same-origin', signal: context.signal, headers: { Range: 'bytes=0-262143' },
        });
        if (!response.ok && response.status !== 206) throw new Error(t('results.textFailed'));
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
        if (!url) throw new Error(t('results.tableNoUrl'));
        const response = await fetch(url, { credentials: 'same-origin', signal: context.signal });
        if (!response.ok) throw new Error(t('results.tableFailed'));
        const page = await response.json() as { columns: unknown[]; rows: unknown[][]; has_more?: boolean };
        const table = document.createElement('table'); table.className = 'result-table';
        const head = document.createElement('thead'); const heading = document.createElement('tr');
        page.columns.forEach((column) => { const cell = document.createElement('th'); cell.scope = 'col'; cell.textContent = String(column); heading.append(cell); });
        head.append(heading); const body = document.createElement('tbody');
        page.rows.forEach((row) => { const line = document.createElement('tr'); row.forEach((value) => { const cell = document.createElement('td'); cell.textContent = String(value ?? ''); line.append(cell); }); body.append(line); });
        table.append(head, body); host.replaceChildren(table);
        if (page.has_more) { const note = document.createElement('p'); note.className = 'result-note'; note.textContent = t('results.tableTruncated'); host.append(note); }
      },
    },
    {
      id: 'download_only',
      async render(_artifact, host) {
        const message = document.createElement('p'); message.className = 'result-empty';
        message.textContent = t('results.downloadOnly'); host.replaceChildren(message);
      },
    },
  ];
}
