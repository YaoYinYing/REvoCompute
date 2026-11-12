import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ResultArtifact } from '../src/api/result-types';
import { createTrajectoryFitPanel } from '../src/features/structure/trajectory-fit-panel';
import type { FitJobInput, FitJobResult } from '../src/features/structure/trajectory-fit-client';
import { fitFrame, toColumnMajorMatrix } from '../src/features/structure/trajectory-fit';
import type { SceneAtom, SceneSnapshot } from '../src/features/structure/molecular-scene';

class TestNode {
  tagName: string;
  className = '';
  textContent = '';
  disabled = false;
  value = '';
  min = '';
  max = '';
  step = '';
  type = '';
  children: TestNode[] = [];
  listeners: Record<string, Array<() => void>> = {};
  attrs = new Map<string, string>();
  constructor(tag: string) { this.tagName = tag.toUpperCase(); }
  setAttribute(name: string, value: string): void { this.attrs.set(name, value); }
  getAttribute(name: string): string | null { return this.attrs.get(name) ?? null; }
  append(...nodes: TestNode[]): void { this.children.push(...nodes); }
  replaceChildren(...nodes: TestNode[]): void { this.children = nodes; }
  addEventListener(type: string, listener: () => void): void { (this.listeners[type] ||= []).push(listener); }
  fire(type: string): void { this.listeners[type]?.forEach((listener) => listener()); }
  all(): TestNode[] { return this.children.flatMap((child) => [child, ...child.all()]); }
}

const TOPOLOGY: ResultArtifact = {
  path: 'topology.pdb', size: 16, sha256: 'b'.repeat(64), url: '/topology.pdb',
  media_type: 'chemical/x-pdb', preview: 'structure', capability: 'molecular_structure', role: 'primary',
};
const COORDINATES: ResultArtifact = {
  path: 'samples.xtc', size: 64, sha256: 'c'.repeat(64), url: '/samples.xtc',
  media_type: 'application/octet-stream', preview: null, capability: 'download_only', role: 'primary',
};

const BASE = [
  { index: 0, serial: 1, name: 'N', chain: 'A', residue: 1, element: 'N', point: [0, 0, 0] },
  { index: 1, serial: 2, name: 'CA', chain: 'A', residue: 1, element: 'C', point: [4, 0, 0] },
  { index: 2, serial: 3, name: 'C', chain: 'A', residue: 1, element: 'C', point: [0, 3, 0] },
  { index: 3, serial: 4, name: 'O', chain: 'B', residue: 42, element: 'O', point: [2, 2, 5] },
];

function sceneAtom(entry: typeof BASE[number]): SceneAtom {
  return {
    identity: {
      authChain: entry.chain, labelChain: entry.chain, authSeqId: entry.residue, labelSeqId: entry.residue,
      residueName: 'ALA', atomName: entry.name, atomSerial: entry.serial, modelIndex: 0, index: entry.index,
    },
    element: entry.element,
    position: { x: entry.point[0]!, y: entry.point[1]!, z: entry.point[2]! },
  };
}

function coordinatesOf(frame: number, indices: readonly number[]): Float64Array {
  const flat = new Float64Array(indices.length * 3);
  indices.forEach((atom, offset) => {
    const entry = BASE.find((candidate) => candidate.index === atom)!;
    flat[offset * 3] = entry.point[0]! + frame;
    flat[offset * 3 + 1] = entry.point[1]!;
    flat[offset * 3 + 2] = entry.point[2]!;
  });
  return flat;
}

interface Harness {
  panel: ReturnType<typeof createTrajectoryFitPanel>;
  apply: ReturnType<typeof vi.fn>;
  selectMode: ReturnType<typeof vi.fn>;
  run: ReturnType<typeof vi.fn>;
  download: ReturnType<typeof vi.fn>;
  snapshot: SceneSnapshot;
  emitScene(event: { type: string }): void;
  node(predicate: (node: TestNode) => boolean): TestNode;
  cell: () => { lengths: [number, number, number] } | null;
}

interface HarnessOptions {
  rejection?: number[];
  box?: { lengths: [number, number, number] };
}

function harness(options: HarnessOptions = {}): Harness {
  vi.stubGlobal('document', { createElement: (tag: string) => new TestNode(tag) });
  const snapshot: SceneSnapshot = {
    topologyRevision: 1, topologyDigest: 'topology-digest', coordinateFrame: 0, units: 'angstrom',
    selectedAtoms: [], selectedResidues: [],
  };
  const apply = vi.fn(async () => undefined);
  const selectMode = vi.fn();
  const download = vi.fn();
  let sceneListener: ((event: { type: string }) => void) | null = null;
  const cell = options.box ?? null;
  const run = vi.fn(async (input: FitJobInput): Promise<FitJobResult> => {
    const transforms = new Float64Array(input.frameCount * 16);
    const rmsd = new Float64Array(input.frameCount);
    for (let frame = 0; frame < input.frameCount; frame += 1) {
      const result = fitFrame(input.reference, input.readFrame(frame), { mode: input.mode });
      transforms.set(toColumnMajorMatrix(result.transform), frame * 16);
      rmsd[frame] = result.rmsd;
    }
    return { transforms, rmsd, rejectedFrames: options.rejection ?? [] };
  });
  const controller = {
    supportsTrajectoryFitting: () => true,
    allAtoms: () => BASE.map(sceneAtom),
    scene: () => ({
      snapshot: () => ({
        ...snapshot,
        selectedAtoms: snapshot.selectedAtoms.map((atom) => ({ ...atom })),
      }),
    }),
    subscribeScene: (listener: (event: { type: string }) => void) => {
      sceneListener = listener;
      return () => { sceneListener = null; };
    },
    readTrajectoryFrame: (frame: number, indices: readonly number[]) => coordinatesOf(frame, indices),
    trajectoryFrameCell: () => cell,
    applyPreviewTransform: apply,
    setSelectionMode: selectMode,
  } as never;
  const panel = createTrajectoryFitPanel({
    controller,
    taskId: 'a'.repeat(32),
    source: () => ({
      topology: TOPOLOGY, coordinates: COORDINATES, coordinateFormat: 'xtc', topologyFormat: 'pdb',
    }),
    createClient: () => ({ run, dispose: vi.fn() } as never),
    download,
  });
  return {
    panel, apply, selectMode, run, download, snapshot,
    emitScene: (event) => sceneListener?.(event),
    node: (predicate) => {
      const found = (panel.element as unknown as TestNode).all().find(predicate);
      if (!found) throw new Error('node not found');
      return found;
    },
    cell: () => cell,
  };
}

function buttonByText(harness: Harness, text: string): TestNode {
  return harness.node((node) => node.tagName === 'BUTTON' && node.textContent === text);
}

function statusNode(harness: Harness): TestNode {
  return harness.node((node) => node.className === 'result-note trajectory-fit-status');
}

/** Wait until the panel has applied an actual preview matrix. */
async function fitted(harness: Harness): Promise<void> {
  await vi.waitFor(() => expect(harness.apply.mock.calls.some((call) => call[0] !== null)).toBe(true));
}

beforeEach(() => vi.useRealTimers());
afterEach(() => vi.unstubAllGlobals());

describe('trajectory fit panel', () => {
  it('fits the whole frame, applies a preview matrix and labels RMSD as a preview metric', async () => {
    const h = harness();
    await h.panel.frameDisplayed(0, 3);
    buttonByText(h, 'Fit and preview').fire('click');
    await vi.waitFor(() => expect(h.run).toHaveBeenCalledTimes(1));
    await fitted(h);
    expect(h.run.mock.calls[0]![0]).toMatchObject({ mode: 'fit', atomCount: 4, frameCount: 3 });
    expect((h.run.mock.calls[0]![0] as FitJobInput).reference).toHaveLength(12);
    const status = statusNode(h);
    expect(status.textContent).toContain('RMSD');
    expect(status.textContent).toContain('preview metric');
    expect(status.textContent).toContain('No periodic box');
  });

  it('uses the shared typed selection when the reader chooses it', async () => {
    const h = harness();
    await h.panel.frameDisplayed(0, 2);
    h.snapshot.selectedAtoms = BASE.slice(0, 3).map(sceneAtom);
    h.emitScene({ type: 'selection' });
    const scope = h.node((node) => node.className === 'trajectory-fit-scope');
    expect(scope.children[1]!.disabled).toBe(false);
    expect(scope.children[1]!.textContent).toBe('Current selection (3 atoms)');
    scope.value = 'selection';
    scope.fire('change');
    buttonByText(h, 'Fit and preview').fire('click');
    await vi.waitFor(() => expect(h.run).toHaveBeenCalledTimes(1));
    expect(h.run.mock.calls[0]![0]).toMatchObject({ atomCount: 3 });
    await vi.waitFor(() => expect(statusNode(h).textContent).toContain('3 atoms'));
  });

  it('runs the explicit center-only mode', async () => {
    const h = harness();
    await h.panel.frameDisplayed(0, 2);
    buttonByText(h, 'Center only').fire('click');
    await vi.waitFor(() => expect(h.run).toHaveBeenCalledTimes(1));
    expect(h.run.mock.calls[0]![0]).toMatchObject({ mode: 'center' });
  });

  it('toggles the viewer selection mode from the shared scene', async () => {
    const h = harness();
    await h.panel.frameDisplayed(0, 2);
    const select = h.node((node) => node.textContent === 'Select atoms');
    select.fire('click');
    expect(h.selectMode).toHaveBeenCalledWith(true);
    expect(select.getAttribute('aria-pressed')).toBe('true');
    select.fire('click');
    expect(h.selectMode).toHaveBeenLastCalledWith(false);
  });

  it('applies the precomputed matrix for a newly displayed frame', async () => {
    const h = harness();
    await h.panel.frameDisplayed(0, 3);
    buttonByText(h, 'Fit and preview').fire('click');
    await fitted(h);
    const first = h.apply.mock.calls.filter((call) => call[0] !== null).at(-1)![0] as Float64Array;
    h.apply.mockClear();
    await h.panel.frameDisplayed(1, 3);
    expect(h.apply).toHaveBeenCalledTimes(1);
    const second = h.apply.mock.calls[0]![0] as Float64Array;
    expect(Array.from(second)).not.toEqual(Array.from(first));
  });

  it('clears the reversible preview and restores the raw display on reset', async () => {
    const h = harness();
    await h.panel.frameDisplayed(0, 2);
    buttonByText(h, 'Fit and preview').fire('click');
    await fitted(h);
    h.apply.mockClear();
    buttonByText(h, 'Reset preview').fire('click');
    expect(h.apply).toHaveBeenCalledWith(null);
    expect(statusNode(h).textContent).toContain('original frame');
  });

  it('drops a cached transform when the topology revision changes', async () => {
    const h = harness();
    await h.panel.frameDisplayed(0, 3);
    buttonByText(h, 'Fit and preview').fire('click');
    await fitted(h);
    h.apply.mockClear();
    h.snapshot.topologyRevision = 2;
    await h.panel.frameDisplayed(1, 3);
    expect(h.apply).toHaveBeenCalledWith(null);
    expect(statusNode(h).textContent).toContain('source changed');
  });

  it('states that a trajectory is too large for browser fitting', async () => {
    const h = harness();
    await h.panel.frameDisplayed(0, 50001);
    buttonByText(h, 'Fit and preview').fire('click');
    await vi.waitFor(() => expect(statusNode(h).textContent).toContain('frames'));
    expect(h.run).not.toHaveBeenCalled();
  });

  it('warns when positions span a declared periodic box and never claims an unwrap', async () => {
    const h = harness({ box: { lengths: [2, 2, 2] } });
    await h.panel.frameDisplayed(0, 2);
    buttonByText(h, 'Fit and preview').fire('click');
    await vi.waitFor(() => expect(statusNode(h).textContent).toContain('periodic box'));
    expect(statusNode(h).textContent).toContain('2.0 × 2.0 × 2.0 Å');
    expect(statusNode(h).textContent).toContain('No unwrap was performed');
  });

  it('exports the aligned frame as a local PDB preview with sidecar metadata', async () => {
    const h = harness();
    await h.panel.frameDisplayed(1, 3);
    buttonByText(h, 'Fit and preview').fire('click');
    await fitted(h);
    buttonByText(h, 'Export aligned frame (PDB)').fire('click');
    expect(h.download).toHaveBeenCalledTimes(2);
    const [pdbName, pdbText, pdbType] = h.download.mock.calls[0]!;
    const [metaName, metaText, metaType] = h.download.mock.calls[1]!;
    expect(pdbName).toBe('samples.frame-2.preview.pdb');
    expect(pdbType).toBe('chemical/x-pdb');
    expect(pdbText).toContain('MODEL        1');
    expect(pdbText).toContain('ATOM  ');
    expect(metaName).toBe('samples.frame-2.preview.metadata.json');
    expect(metaType).toBe('application/json');
    const metadata = JSON.parse(metaText);
    expect(metadata.source.coordinates.sha256).toBe('c'.repeat(64));
    expect(metadata.source.topology.sha256).toBe('b'.repeat(64));
    expect(metadata.source.taskId).toBe('a'.repeat(32));
    expect(metadata.frame).toEqual({ index: 1, count: 3 });
    expect(metadata.fit.mode).toBe('fit');
    expect(metadata.fit.atomCount).toBe(4);
    expect(metadata.transform).not.toBeNull();
    expect(statusNode(h).textContent).toContain('not a server-published result');
  });

  it('refuses to export before a preview fit exists', async () => {
    const h = harness();
    await h.panel.frameDisplayed(0, 2);
    buttonByText(h, 'Export aligned frame (PDB)').fire('click');
    expect(h.download).not.toHaveBeenCalled();
    expect(statusNode(h).textContent).toContain('Apply a preview fit');
  });

  it('invalidates the preview when the typed selection changes', async () => {
    const h = harness();
    await h.panel.frameDisplayed(0, 2);
    buttonByText(h, 'Fit and preview').fire('click');
    await fitted(h);
    h.apply.mockClear();
    h.emitScene({ type: 'selection' });
    expect(h.apply).toHaveBeenCalledWith(null);
    expect(statusNode(h).textContent).toContain('Selection changed');
  });
});
