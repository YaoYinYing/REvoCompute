import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ResultArtifact } from '../src/api/result-types';
import { createTrajectoryViewRenderer } from '../src/features/results/trajectory-view';
import type { MolecularViewer } from '../src/features/results/molecular/viewer-contract';

class TestNode {
  className = '';
  textContent = '';
  hidden = false;
  disabled = false;
  value = '';
  max = '';
  min = '';
  step = '';
  type = '';
  dataset: Record<string, string> = {};
  children: TestNode[] = [];
  listeners: Record<string, Array<() => void>> = {};
  setAttribute(): void {}
  append(...nodes: TestNode[]): void { this.children.push(...nodes); }
  replaceChildren(...nodes: TestNode[]): void { this.children = nodes; }
  addEventListener(type: string, listener: () => void): void { (this.listeners[type] ||= []).push(listener); }
  fire(type: string): void { this.listeners[type]?.forEach((listener) => listener()); }
  all(): TestNode[] { return this.children.flatMap((child) => [child, ...child.all()]); }
}

const source = (path: string, size = 8): ResultArtifact => ({
  path, size, sha256: 'a'.repeat(64), url: `/${path}`, media_type: 'application/octet-stream',
  preview: null, capability: 'download_only', role: 'primary',
});

const view = {
  id: 'ensemble', plugin: 'trajectory', role: 'primary', title: 'Ensemble',
  description: 'Sampled conformations.', sources: { topology: ['topology.pdb'], coordinates: ['samples.xtc'] },
  mapping: { coordinate_format: 'xtc', frame_unit: 'sample', timestep: 1, association: 'single' },
};

afterEach(() => vi.unstubAllGlobals());

function installGlobals(): TestNode {
  const host = new TestNode();
  vi.stubGlobal('document', { createElement: () => new TestNode() });
  vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(url === '/topology.pdb' ? 'ATOM' : new Uint8Array([1, 2]))));
  return host;
}

function viewer(overrides: Partial<MolecularViewer> = {}): MolecularViewer {
  return {
    setRepresentation: async () => {}, setColor: async () => {}, setTheme: () => {}, resize: () => {},
    captureImage: async () => '', dispose: () => {}, loadStructure: async () => {},
    loadTrajectory: async () => ({ frame: 0, frameCount: 23 }),
    setTrajectoryFrame: async (action, value) => ({ frame: action === 'set' ? value : value, frameCount: 23 }),
    ...overrides,
  };
}

function nodes(host: TestNode): { scrubber: TestNode; previous: TestNode; next: TestNode; position: TestNode; status: TestNode } {
  const all = host.all();
  return {
    scrubber: all.find((node) => node.className === 'trajectory-scrubber')!,
    previous: all.find((node) => node.dataset.trajectory === 'previous')!,
    next: all.find((node) => node.dataset.trajectory === 'next')!,
    position: all.find((node) => node.className === 'trajectory-position')!,
    status: all.find((node) => node.className.includes('trajectory-status'))!,
  };
}

describe('trajectory view renderer', () => {
  it('feeds both declared sources to one stage and labels the axis Sample index, not time', async () => {
    const host = installGlobals();
    const renderer = createTrajectoryViewRenderer(async () => viewer(), () => 'light');
    const handle = await renderer.render(view as never, { topology: [source('topology.pdb')], coordinates: [source('samples.xtc')] }, host as never, {
      signal: new AbortController().signal, taskId: 'a'.repeat(32),
    });
    const parts = nodes(host);
    expect(parts.scrubber.disabled).toBe(false);
    expect(parts.scrubber.max).toBe('23');
    expect(parts.position.textContent).toBe('Sample index 1 of 23');
    expect(parts.status.textContent).toBe('23 frames loaded. Sample order is not physical time.');
    expect((handle as { destroy(): void }).destroy).toBeTypeOf('function');
  });

  it('labels a declared diffusion-step axis as diffusion steps, with no physical-time claim', async () => {
    const host = installGlobals();
    const renderer = createTrajectoryViewRenderer(async () => viewer({
      loadTrajectory: async () => ({ frame: 0, frameCount: 15 }),
    }), () => 'light');
    const diffusion = {
      ...view, id: 'diffusion_trajectory', plugin: 'trajectory', title: 'Diffusion trajectories',
      sources: { topology: ['design_0.pdb'], coordinates: ['traj/design_0_pX0_traj.pdb'] },
      mapping: { coordinate_format: 'pdb', frame_unit: 'diffusion step', timestep: 1, association: 'stem-prefix' },
    };
    await renderer.render(diffusion as never, { topology: [source('design_0.pdb')], coordinates: [source('traj/design_0_pX0_traj.pdb')] }, host as never, {
      signal: new AbortController().signal, taskId: 'a'.repeat(32),
    });
    const parts = nodes(host);
    expect(parts.position.textContent).toBe('diffusion step 1 of 15');
    expect(parts.status.textContent).toBe('15 frames loaded; one frame is one diffusion step.');
    expect(parts.status.textContent).not.toContain('physical time');
    expect(parts.previous.textContent).toBe('Previous frame');
    expect(parts.next.textContent).toBe('Next frame');
  });

  it('advances the frame without remounting the stage or fabricating time', async () => {
    const host = installGlobals();
    const steps: Array<[string, number]> = [];
    const renderer = createTrajectoryViewRenderer(async () => viewer({
      setTrajectoryFrame: async (action, value) => { steps.push([action, value]); return { frame: 1, frameCount: 23 }; },
    }), () => 'light');
    await renderer.render(view as never, { topology: [source('topology.pdb')], coordinates: [source('samples.xtc')] }, host as never, {
      signal: new AbortController().signal, taskId: 'a'.repeat(32),
    });
    nodes(host).next.fire('click');
    await vi.waitFor(() => expect(nodes(host).position.textContent).toBe('Sample index 2 of 23'));
    expect(steps).toEqual([['advance', 1]]);
    expect(nodes(host).status.textContent).toContain('Sample order is not physical time');
  });

  it('states a missing topology or a failed coordinate fetch explicitly', async () => {
    installGlobals();
    const renderer = createTrajectoryViewRenderer(async () => viewer(), () => 'light');
    const context = { signal: new AbortController().signal, taskId: 'a'.repeat(32) };
    await expect(renderer.render(view as never, { coordinates: [source('samples.xtc')] }, new TestNode() as never, context))
      .rejects.toThrow('no topology artifact');
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/topology.pdb' ? new Response('ATOM') : new Response('gone', { status: 404 })));
    await expect(renderer.render(view as never, { topology: [source('topology.pdb')], coordinates: [source('samples.xtc')] }, new TestNode() as never, context))
      .rejects.toThrow('Coordinate download failed (HTTP 404)');
  });
});
