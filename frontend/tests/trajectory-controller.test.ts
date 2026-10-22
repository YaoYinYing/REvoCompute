import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ResultArtifact } from '../src/api/result-types';
import { StructureController } from '../src/features/results/molecular/structure-controller';
import type { MolecularViewer } from '../src/features/results/molecular/viewer-contract';

const file = (path: string, size = 8): ResultArtifact => ({
  path, size, sha256: 'a'.repeat(64), url: `/${path}`, media_type: 'application/octet-stream',
  preview: null, capability: 'download_only', role: 'primary',
});
afterEach(() => vi.unstubAllGlobals());

function trajectoryViewer(overrides: Partial<MolecularViewer> = {}): MolecularViewer & {
  loads: Array<Record<string, unknown>>;
} {
  const loads: Array<Record<string, unknown>> = [];
  return Object.assign({
    loads,
    setRepresentation: async () => {},
    setColor: async () => {},
    setTheme: () => {},
    resize: () => {},
    captureImage: async () => '',
    dispose: () => {},
    loadStructure: async () => {},
    loadTrajectory: async (source: { topology: string; coordinates: string | Uint8Array; coordinateFormat: string }) => {
      loads.push({ topology: source.topology, coordinates: source.coordinates, format: source.coordinateFormat });
      return { frame: 0, frameCount: 24 };
    },
    setTrajectoryFrame: async (action: 'set' | 'advance', value: number) => ({
      frame: action === 'set' ? value : value, frameCount: 24,
    }),
  } as MolecularViewer & { loads: Array<Record<string, unknown>> }, overrides);
}

describe('StructureController trajectory loading', () => {
  it('reads the topology as text and the coordinates as bytes, then steps one stage', async () => {
    const viewer = trajectoryViewer();
    const fetchMock = vi.fn(async (url: string) => new Response(
      url === '/topology.pdb' ? 'ATOM      1  N   MET A   1' : new Uint8Array([1, 2, 3, 4]),
    ));
    vi.stubGlobal('fetch', fetchMock);
    const controller = new StructureController(async () => viewer);

    const info = await controller.mountTrajectory(
      {} as HTMLElement, file('topology.pdb'), file('samples.xtc'), 'xtc', 'light',
    );
    expect(info).toEqual({ frame: 0, frameCount: 24 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(viewer.loads).toEqual([{ topology: 'ATOM      1  N   MET A   1', coordinates: new Uint8Array([1, 2, 3, 4]), format: 'xtc' }]);
    await expect(controller.setTrajectoryFrame('advance', 1)).resolves.toEqual({ frame: 1, frameCount: 24 });
  });

  it('refuses an oversized coordinate payload before it reaches the viewer', async () => {
    const createViewer = vi.fn(async () => trajectoryViewer());
    vi.stubGlobal('fetch', vi.fn(async () => new Response('unused')));
    const controller = new StructureController(createViewer);

    await expect(controller.mountTrajectory(
      {} as HTMLElement, file('topology.pdb'), file('samples.xtc', 64 * 1024 * 1024 + 1), 'xtc', 'light',
    )).rejects.toThrow('safe inline preview limit');
    expect(createViewer).not.toHaveBeenCalled();
  });

  it('states which fetch failed instead of showing an empty stage', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/topology.pdb'
      ? new Response('ATOM', { status: 200 })
      : new Response('missing', { status: 404 })));
    const controller = new StructureController(async () => trajectoryViewer());

    await expect(controller.mountTrajectory(
      {} as HTMLElement, file('topology.pdb'), file('samples.xtc'), 'xtc', 'light',
    )).rejects.toThrow('Coordinate download failed (HTTP 404)');
  });

  it('reports that frame navigation is unavailable when the viewer cannot step', async () => {
    const viewer = trajectoryViewer({ setTrajectoryFrame: undefined });
    const controller = new StructureController(async () => viewer);
    await expect(controller.setTrajectoryFrame('advance', 1)).rejects.toThrow('cannot display coordinate frames');
  });
});
