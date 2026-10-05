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

  it('forwards a residue collection and a spatial focus target to the viewer', async () => {
    const select = vi.fn(() => true); const focus = vi.fn(() => true);
    const viewer: MolecularViewer = { setRepresentation: async () => {}, setColor: async () => {}, setTheme: () => {}, resize: () => {}, captureImage: async () => '', dispose: () => {},
      loadStructure: async () => {}, select, focus };
    vi.stubGlobal('fetch', vi.fn(async () => new Response('ATOM')));
    const controller = new StructureController(async () => viewer);
    await controller.mount({} as HTMLElement, file('model.pdb'), 'light');

    // A multi-residue collection crosses the boundary as ONE call, so the adapter
    // builds a single combined selection instead of N replacing selections.
    const residues = [{ chain: 'A', residue: 101, numbering: 'label_seq_id' }, { chain: 'A', residue: 104, numbering: 'label_seq_id' }];
    expect(controller.select({ residues })).toBe(true);
    expect(select).toHaveBeenCalledTimes(1);
    expect(select).toHaveBeenCalledWith({ residues });

    // A spatial focus target crosses as a point the adapter focuses on.
    const focusPoint = { x: -17.4, y: 89.4, z: 4.4, radius: 6 };
    expect(controller.focus({ focusPoint })).toBe(true);
    expect(focus).toHaveBeenCalledWith({ focusPoint });
  });

  it('carries author numbering and insertion codes through unchanged', async () => {
    const select = vi.fn(() => true);
    const viewer: MolecularViewer = { setRepresentation: async () => {}, setColor: async () => {}, setTheme: () => {}, resize: () => {}, captureImage: async () => '', dispose: () => {},
      loadStructure: async () => {}, select };
    vi.stubGlobal('fetch', vi.fn(async () => new Response('ATOM')));
    const controller = new StructureController(async () => viewer);
    await controller.mount({} as HTMLElement, file('model.pdb'), 'light');

    // A residue with an insertion code (auth numbering) is forwarded verbatim, so
    // the adapter can match 42A as distinct from 42.
    const residues = [
      { chain: 'A', residue: 42, insertionCode: 'A', numbering: 'auth_seq_id' as const },
      { chain: 'A', residue: 50, numbering: 'auth_seq_id' as const },
    ];
    controller.select({ residues });
    expect(select).toHaveBeenCalledWith({ residues });
    expect(residues[0]!.insertionCode).toBe('A');
    expect('insertionCode' in residues[1]!).toBe(false);
  });
});
