import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ResultArtifact } from '../src/api/result-types';
import { StructureController } from '../src/features/results/molecular/structure-controller';
import type { MolecularViewer } from '../src/features/results/molecular/viewer-contract';

const file = (path: string): ResultArtifact => ({ path, size: 8, sha256: 'a'.repeat(64), url: `/${path}`, media_type: 'chemical/x-pdb', preview: 'structure', capability: 'molecular_structure', role: 'primary' });
afterEach(() => vi.unstubAllGlobals());

describe('StructureController', () => {
  it('serializes non-abortable viewer mutations so the latest candidate finishes last', async () => {
    let releaseFirst!: () => void; const firstLoad = new Promise<void>((resolve) => { releaseFirst = resolve; }); const loaded: string[] = [];
    const viewer: MolecularViewer = { setRepresentation: async () => {}, setColor: async () => {}, setTheme: () => {}, resize: () => {}, captureImage: async () => '', dispose: () => {},
      loadStructure: async (source) => { loaded.push(source.label || ''); if (source.label === 'first.pdb') await firstLoad; } };
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(url)));
    const controller = new StructureController(async () => viewer); const host = {} as HTMLElement;
    const first = controller.mount(host, file('first.pdb'), 'light'); await vi.waitFor(() => expect(loaded).toEqual(['first.pdb']));
    const second = controller.mount(host, file('second.pdb'), 'light'); releaseFirst(); await Promise.all([first, second]);
    expect(loaded).toEqual(['first.pdb', 'second.pdb']);
  });

  it('retries viewer creation after an isolated mount failure', async () => {
    const viewer: MolecularViewer = { setRepresentation: async () => {}, setColor: async () => {}, setTheme: () => {}, resize: () => {}, captureImage: async () => '', dispose: vi.fn(), loadStructure: async () => {} };
    const createViewer = vi.fn()
      .mockRejectedValueOnce(new Error('WebGL unavailable'))
      .mockResolvedValueOnce(viewer);
    vi.stubGlobal('fetch', vi.fn(async () => new Response('ATOM')));
    const controller = new StructureController(createViewer); const host = {} as HTMLElement;

    await expect(controller.mount(host, file('first.pdb'), 'light')).rejects.toThrow('WebGL unavailable');
    await expect(controller.mount(host, file('second.pdb'), 'light')).resolves.toBeUndefined();
    expect(createViewer).toHaveBeenCalledTimes(2);
  });
});
