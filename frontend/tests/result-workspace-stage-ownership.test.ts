import { afterEach, describe, expect, it, vi } from 'vitest';

// A Task Storyboard in miniature: it owns a `[data-structure-slot]` stage, mounts
// the published structure there through `services.openFile`, then mounts its own
// declared candidate view over that same artifact through `services.mountView`.
declare global {
  // The published path the probe storyboard draws; unset draws the logical file
  // the manifest declares.
  var __storyboardDrawnPath: string | undefined;
}

vi.mock('storyboard-probe', () => ({
  default: {
    async mount(host: HTMLElement, context: {
      files: { get(id: string): { path: string } };
      services: { openFile(file: unknown): Promise<void>; mountView(id: string, host: HTMLElement, signal: AbortSignal): Promise<unknown> };
    }) {
      const slot = document.createElement('div'); slot.dataset.structureSlot = 'true';
      const viewHost = document.createElement('section');
      host.replaceChildren(slot, viewHost);
      const file = context.files.get('models');
      const drawn = globalThis.__storyboardDrawnPath;
      await context.services.openFile(drawn ? { ...file, path: drawn } : file);
      await context.services.mountView('models', viewHost, new AbortController().signal);
      return { destroy() {} };
    },
  },
}));

import type { ResultArtifact } from '../src/api/result-types';
import { ResultWorkspace } from '../src/features/results/ResultWorkspace';
import type { MolecularViewer } from '../src/features/results/molecular/viewer-contract';
import { HarnessNode, installHarness } from './dom-harness';

const TASK = '0123456789abcdef0123456789abcdef';
const artifact = (path: string, extra: Record<string, unknown> = {}): ResultArtifact & Record<string, unknown> => ({
  path, size: 8, sha256: 'a'.repeat(64), url: `/artifacts/${path}`, media_type: 'text/plain',
  preview: 'text', capability: 'text', role: 'primary', ...extra,
} as ResultArtifact & Record<string, unknown>);

const candidate = artifact('models/model_0.cif', { media_type: 'chemical/x-cif', preview: 'structure', capability: 'molecular_structure' });
const summary = artifact('summary.txt');
const views = [
  { id: 'models', plugin: 'candidate-collection', role: 'primary', title: 'Models', sources: { candidates: [candidate.path] }, mapping: {} },
  { id: 'summary', plugin: 'evidence-bundle', role: 'evidence', title: 'Summary', sources: { items: [summary.path] }, mapping: {} },
];
const manifest = { schema_version: 3, task_id: TASK, task_type: 'demo', created_at: '2026-10-22T00:00:00Z',
  status: 'finished', terminal: true, error: null, artifacts: [candidate, summary], total_size: 16, limitations: [],
  views,
  run: { method: { name: 'Demo' }, inputs: [], parameters: [], citations: [] },
  output_check: { state: 'passed', checks: [], problems: [] },
  archive: { ready: false, request_url: `/compute/api/results/${TASK}/archive`, download_url: null },
  storyboard: null, result: { files: {} }, outcome: 'SUCCESS' };
const status = { task_id: TASK, task_type: 'demo', display_name: 'demo', status: 'finished', terminal: true,
  result_available: true, status_url: '', results_url: '' };

/** The harness needs an `<option>` that behaves like the element `new Option` builds. */
class OptionNode extends HarnessNode {
  text: string; value: string;
  constructor(text: string, value: string) { super('option'); this.text = text; this.value = value; }
}

afterEach(() => vi.unstubAllGlobals());

describe('ResultWorkspace molecular stage ownership', () => {
  it('disposes the shared viewer when a candidate view is superseded and remounts on return', async () => {
    installHarness(vi.stubGlobal, { pathname: `/compute/results/${TASK}` });
    vi.stubGlobal('Option', OptionNode);
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/auth/me')) return new Response(JSON.stringify({ id: 1, username: 'owner' }));
      if (url.includes('/running/')) return new Response(JSON.stringify(status));
      if (url.endsWith(`/results/${TASK}`)) return new Response(JSON.stringify(manifest));
      return new Response('ATOM');
    }));
    let mounts = 0; let disposals = 0;
    const viewer = (): MolecularViewer => ({ setRepresentation: async () => {}, setColor: async () => {}, setTheme: () => {},
      resize: () => {}, captureImage: async () => '', loadStructure: async () => {}, dispose: () => { disposals += 1; } });
    const root = document.createElement('div') as unknown as HarnessNode;
    const workspace = new ResultWorkspace(root as unknown as HTMLElement, async () => { mounts += 1; return viewer(); });
    const search = root.querySelector('.result-search') as unknown as { value: string };
    search.value = '';

    await workspace.load();
    expect(root.querySelector('.candidate-stage')).not.toBeNull();
    expect(mounts).toBe(1);

    await (workspace as unknown as { openView(view: unknown): Promise<void> })
      .openView((manifest.views as unknown[])[1]);
    expect(disposals).toBe(1);
    expect(root.querySelector('.candidate-stage')).toBeNull();

    await (workspace as unknown as { openView(view: unknown): Promise<void> })
      .openView((manifest.views as unknown[])[0]);
    expect(root.querySelector('.candidate-stage')).not.toBeNull();
    expect(mounts).toBe(2);
  });

  it('does not let a declared view dispossess the structure the page already draws', async () => {
    // The Task Storyboard mounts `models/model_0.cif` in its own slot through
    // openFile, then mounts its declared candidate-collection view, which lists
    // that same artifact. One shared StructureController mounts one host, so a
    // mount into the view's `.candidate-stage` would dispose the page's own stage
    // and leave the slot empty while the declared view showed the model.
    installHarness(vi.stubGlobal, { pathname: `/compute/results/${TASK}` });
    vi.stubGlobal('Option', OptionNode);
    const storyboard = { identifier: 'demo', entrypoint: 'index.js', entrypoint_url: 'storyboard-probe', requires: ['models'], optional: [] };
    const storyboardManifest = { ...manifest, storyboard,
      result: { files: { models: [{ ...candidate, id: 'models', name: 'model_0.cif', path: candidate.path, cardinality: 'one', viewer: 'structure' }] } } };
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/auth/me')) return new Response(JSON.stringify({ id: 1, username: 'owner' }));
      if (url.includes('/running/')) return new Response(JSON.stringify(status));
      if (url.endsWith(`/results/${TASK}`)) return new Response(JSON.stringify(storyboardManifest));
      return new Response('ATOM');
    }));
    let mounts = 0; let disposals = 0;
    const viewer = (): MolecularViewer => ({ setRepresentation: async () => {}, setColor: async () => {}, setTheme: () => {},
      resize: () => {}, captureImage: async () => '', loadStructure: async () => {}, dispose: () => { disposals += 1; } });
    const root = document.createElement('div') as unknown as HarnessNode;
    const workspace = new ResultWorkspace(root as unknown as HTMLElement, async () => { mounts += 1; return viewer(); });
    (root.querySelector('.result-search') as unknown as { value: string }).value = '';

    // `load()` renders the manifest through the storyboard, as the route does.
    await workspace.load();
    await vi.waitFor(() => expect(root.querySelector('[data-structure-slot]')).not.toBeNull());
    await vi.waitFor(() => expect(root.querySelector('.candidate-collection-view')).not.toBeNull());

    // The storyboard's own slot keeps the one mounted stage, and the declared
    // view states the artifact instead of mounting it a second time.
    expect(root.querySelector('[data-structure-slot] .structure-host')).not.toBeNull();
    expect(root.querySelector('.candidate-stage')).toBeNull();
    expect(mounts).toBe(1);
    expect(disposals).toBe(0);
    expect(root.textContent).toContain('drawn in the page’s own structure stage above');
  });

  it('mounts a candidate whose published path only shares a basename with the drawn structure', async () => {
    // The Storyboard draws `run2/model_0.cif`; the declared view lists
    // `run1/model_0.cif`. Same basename, different published artifact: the page
    // does not draw this one, so the view must mount the selected structure.
    installHarness(vi.stubGlobal, { pathname: `/compute/results/${TASK}` });
    vi.stubGlobal('Option', OptionNode);
    globalThis.__storyboardDrawnPath = 'run2/model_0.cif';
    const drawn = artifact('run2/model_0.cif', { media_type: 'chemical/x-cif', preview: 'structure', capability: 'molecular_structure' });
    const listed = artifact('run1/model_0.cif', { media_type: 'chemical/x-cif', preview: 'structure', capability: 'molecular_structure' });
    const storyboard = { identifier: 'demo', entrypoint: 'index.js', entrypoint_url: 'storyboard-probe', requires: ['models'], optional: [] };
    const storyboardManifest = { ...manifest, artifacts: [drawn, listed],
      views: [{ ...views[0]!, sources: { candidates: [listed.path] } }], storyboard,
      result: { files: { models: [{ ...drawn, id: 'models', name: 'model_0.cif', path: drawn.path, cardinality: 'one', viewer: 'structure' }] } } };
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/auth/me')) return new Response(JSON.stringify({ id: 1, username: 'owner' }));
      if (url.includes('/running/')) return new Response(JSON.stringify(status));
      if (url.endsWith(`/results/${TASK}`)) return new Response(JSON.stringify(storyboardManifest));
      return new Response('ATOM');
    }));
    let mounts = 0; const loaded: string[] = [];
    const viewer = (): MolecularViewer => ({ setRepresentation: async () => {}, setColor: async () => {}, setTheme: () => {},
      resize: () => {}, captureImage: async () => '', dispose: () => {},
      loadStructure: async (source) => { loaded.push(source.label || ''); } });
    const root = document.createElement('div') as unknown as HarnessNode;
    const workspace = new ResultWorkspace(root as unknown as HTMLElement, async () => { mounts += 1; return viewer(); });
    (root.querySelector('.result-search') as unknown as { value: string }).value = '';

    try {
      await workspace.load();
      await vi.waitFor(() => expect(root.querySelector('.candidate-stage .structure-host')).not.toBeNull());
      // The page's own stage stays mounted and the declared view mounts its own.
      expect(root.querySelector('[data-structure-slot] .structure-host')).not.toBeNull();
      expect(loaded).toContain('run1/model_0.cif');
      expect(root.textContent).not.toContain('drawn in the page’s own structure stage above');
      expect(mounts).toBe(2);
    } finally { globalThis.__storyboardDrawnPath = undefined; }
  });

  it('mounts the declared candidate when the page structure it names failed to load', async () => {
    // The Storyboard hands the same artifact to openFile and to the declared view,
    // but the page's own fetch of it fails. A mount that never landed is not a
    // structure the page draws, so the view must still mount its own stage.
    installHarness(vi.stubGlobal, { pathname: `/compute/results/${TASK}` });
    vi.stubGlobal('Option', OptionNode);
    const storyboard = { identifier: 'demo', entrypoint: 'index.js', entrypoint_url: 'storyboard-probe', requires: ['models'], optional: [] };
    const storyboardManifest = { ...manifest, storyboard,
      result: { files: { models: [{ ...candidate, id: 'models', name: 'model_0.cif', path: candidate.path, cardinality: 'one', viewer: 'structure' }] } } };
    let pageStructureFetches = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/auth/me')) return new Response(JSON.stringify({ id: 1, username: 'owner' }));
      if (url.includes('/running/')) return new Response(JSON.stringify(status));
      if (url.endsWith(`/results/${TASK}`)) return new Response(JSON.stringify(storyboardManifest));
      if (url.endsWith(`/artifacts/${candidate.path}`)) {
        pageStructureFetches += 1;
        if (pageStructureFetches === 1) return new Response('unavailable', { status: 500 });
      }
      return new Response('ATOM');
    }));
    let mounts = 0; const loaded: string[] = [];
    const viewer = (): MolecularViewer => ({ setRepresentation: async () => {}, setColor: async () => {}, setTheme: () => {},
      resize: () => {}, captureImage: async () => '', dispose: () => {},
      loadStructure: async (source) => { loaded.push(source.label || ''); } });
    const root = document.createElement('div') as unknown as HarnessNode;
    const workspace = new ResultWorkspace(root as unknown as HTMLElement, async () => { mounts += 1; return viewer(); });
    (root.querySelector('.result-search') as unknown as { value: string }).value = '';

    await workspace.load();
    await vi.waitFor(() => expect(root.querySelector('.candidate-stage .structure-host')).not.toBeNull());
    // The declared candidate was mounted into its own stage after the page's
    // failed attempt left nothing drawn.
    expect(loaded).toEqual([candidate.path]);
    expect(mounts).toBe(2);
  });
});
