import { OrderedSet } from 'molstar/lib/mol-data/int.js';
import { Sphere3D } from 'molstar/lib/mol-math/geometry.js';
import { Vec3 } from 'molstar/lib/mol-math/linear-algebra/3d/vec3.js';
import {
  StructureElement,
  StructureProperties,
} from 'molstar/lib/mol-model/structure.js';
import { StateTransforms } from 'molstar/lib/mol-plugin-state/transforms.js';
import { PluginUIContext } from 'molstar/lib/mol-plugin-ui/context.js';
import { Plugin } from 'molstar/lib/mol-plugin-ui/plugin.js';
import { DefaultPluginUISpec } from 'molstar/lib/mol-plugin-ui/spec.js';
import { loadTrajectory as loadPluginTrajectory } from 'molstar/lib/extensions/plugin/loaders.js';
import { createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import 'molstar/build/viewer/molstar.css';

const REPRESENTATIONS: Record<string, string> = {
  cartoon: 'cartoon',
  cartoon_ligand: 'polymer-and-ligand',
  sticks: 'ball-and-stick',
  surface_ligand: 'molecular-surface',
};

const COMPOSED_REPRESENTATIONS = new Set(['cartoon_ligand']);
const COLORS: Record<string, string> = {
  chain: 'chain-id',
  rainbow: 'sequence-id',
  confidence: 'plddt-confidence',
  plddt: 'plddt-confidence',
};

const BACKGROUNDS = { light: 0xf8faf7, dark: 0x111318 } as const;

export interface StructureSource {
  data: string;
  format: 'pdb' | 'mmcif';
  label?: string;
}

export interface MolecularSelection {
  chain?: string;
  entity?: string;
  residue?: number;
  numbering?: 'auth_seq_id' | 'label_seq_id';
  /** PDB insertion code: it distinguishes e.g. residue 42A from residue 42.
   *
   *  Omit it to match the residue regardless of insertion code; pass an empty
   *  string to require the bare residue (no insertion code); pass a non-empty
   *  string to require that exact code. */
  insertionCode?: string;
  /** A bounded set of residues selected together as one operation. */
  residues?: MolecularSelection[];
  /** A spatial focus target: a Cartesian point (Angstrom) and optional radius (Angstrom). */
  focusPoint?: { x: number; y: number; z: number; radius?: number };
}

export interface SelectedResidue {
  /** Stable molecular identity: label_asym_id plus label_seq_id. */
  chain: string;
  residue: number;
  auth_seq_id: number;
  label_seq_id: number;
  /** PDB insertion code ('' when absent), part of the residue identity. */
  insertion_code?: string;
}

export interface MolecularViewerOptions {
  showControls?: boolean;
  selectionEnabled?: boolean;
  theme?: 'light' | 'dark';
}

type SelectionListener = (residues: SelectedResidue[]) => void;

export class MolecularViewer {
  private plugin: any = null;
  private reactRoot: Root | null = null;
  private host: HTMLElement | null = null;
  private hostPosition: string | null = null;
  private options: MolecularViewerOptions = {};
  private representation = 'cartoon';
  private color = 'chain';
  private appliedRepresentation: string | null = null;
  private operation = Promise.resolve();
  private selectionSubscription: { unsubscribe(): void } | null = null;
  private selectionListeners = new Set<SelectionListener>();
  private resizeObserver: ResizeObserver | null = null;
  private disposed = false;

  static async mount(host: HTMLElement, options: MolecularViewerOptions = {}) {
    const viewer = new MolecularViewer();
    await viewer.mount(host, options);
    return viewer;
  }

  async mount(host: HTMLElement, options: MolecularViewerOptions = {}) {
    if (this.plugin) throw new Error('MolecularViewer is already mounted');
    this.host = host;
    if (getComputedStyle(host).position === 'static') {
      this.hostPosition = host.style.position;
      host.style.position = 'relative';
    }
    this.options = options;
    const spec = DefaultPluginUISpec();
    spec.layout = {
      ...spec.layout,
      initial: {
        ...spec.layout?.initial,
        isExpanded: false,
        showControls: true,
        controlsDisplay: 'reactive',
        regionState: {
          left: 'hidden',
          top: options.selectionEnabled ? 'full' : 'hidden',
          right: options.showControls ? 'full' : 'hidden',
          bottom: 'hidden',
        },
      },
    };
    spec.components = {
      ...spec.components,
      remoteState: 'none',
      controls: {
        ...spec.components?.controls,
        top: options.selectionEnabled ? spec.components?.controls?.top : 'none',
        left: 'none',
        right: options.showControls ? spec.components?.controls?.right : 'none',
        bottom: 'none',
      },
    };
    const plugin = new PluginUIContext(spec);
    this.plugin = plugin;
    try {
      await plugin.init();
      this.reactRoot = createRoot(host);
      this.reactRoot.render(createElement(Plugin, { plugin }));
      try { await plugin.canvas3dInitialized; } catch { /* Mol* reports canvas failures through its UI. */ }
      plugin.selectionMode = Boolean(options.selectionEnabled);
      this.setTheme(options.theme || 'light');
      this.selectionSubscription = plugin.managers.structure.selection.events.changed.subscribe(() => {
        const residues = this.selectedResidues();
        this.selectionListeners.forEach(listener => listener(residues));
      });
      if (typeof ResizeObserver !== 'undefined') {
        this.resizeObserver = new ResizeObserver(() => this.resize());
        this.resizeObserver.observe(host);
      }
    } catch (error) {
      try { this.releaseResources(); } catch { /* Preserve the initialization error. */ }
      throw error;
    }
    return this;
  }

  loadStructure(source: StructureSource) {
    return this.enqueue(async () => {
      this.assertMounted();
      await this.plugin.clear();
      const raw = await this.plugin.builders.data.rawData({ data: source.data, label: source.label || 'structure' });
      const trajectory = await this.plugin.builders.structure.parseTrajectory(raw, source.format);
      await this.plugin.builders.structure.hierarchy.applyPreset(trajectory, 'default');
      this.appliedRepresentation = null;
      await this.applyPresentation();
    });
  }

  loadTrajectory(source: {
    topology: string;
    coordinates: string | Uint8Array;
    coordinateFormat: string;
    label?: string;
  }) {
    return this.enqueue(async () => {
      this.assertMounted();
      await this.plugin.clear();
      if (source.coordinateFormat === 'pdb') {
        const raw = await this.plugin.builders.data.rawData({ data: source.coordinates, label: source.label || 'trajectory' });
        const trajectory = await this.plugin.builders.structure.parseTrajectory(raw, 'pdb');
        await this.plugin.builders.structure.hierarchy.applyPreset(trajectory, 'default');
      } else {
        await loadPluginTrajectory(this.plugin, {
          model: { kind: 'model-data', data: source.topology, format: 'pdb' },
          modelLabel: 'Declared topology',
          coordinates: {
            kind: 'coordinates-data',
            data: source.coordinates,
            format: source.coordinateFormat,
          },
          coordinatesLabel: source.label || 'coordinates',
          preset: 'default',
        } as any);
      }
      return this.trajectoryInfo();
    });
  }

  setTrajectoryFrame(action: 'set' | 'advance', value: number) {
    return this.enqueue(async () => {
      const info = this.trajectoryInfo();
      if (!info) throw new Error('Mol* did not create a trajectory');
      let frame = action === 'set' ? Number(value) : info.frame + Number(value || 0);
      frame = ((Math.round(frame) % info.frameCount) + info.frameCount) % info.frameCount;
      const update = this.plugin.state.data.build();
      update.to(info.model).update({ modelIndex: frame });
      await this.plugin.state.data.updateTree(update).run();
      return { frame, frameCount: info.frameCount };
    });
  }

  clear() {
    return this.enqueue(async () => {
      this.assertMounted();
      await this.plugin.clear();
      this.appliedRepresentation = null;
    });
  }

  setRepresentation(mode: string) {
    if (!REPRESENTATIONS[mode]) return Promise.reject(new Error(`Unknown representation: ${mode}`));
    this.representation = mode;
    return this.enqueue(() => this.applyPresentation());
  }

  setColor(mode: string) {
    if (!COLORS[mode]) return Promise.reject(new Error(`Unknown color mode: ${mode}`));
    this.color = mode;
    return this.enqueue(() => this.applyColor());
  }

  select(selection: MolecularSelection) {
    const loci = this.lociFor(selection);
    if (!loci) return false;
    // One combined loci, one 'set': a multi-residue selection replaces the
    // previous selection in a single operation rather than accumulating calls.
    this.plugin.managers.structure.selection.fromLoci('set', loci, false);
    return true;
  }

  focus(selection: MolecularSelection) {
    if (selection && selection.focusPoint) return this.focusPoint(selection.focusPoint);
    const loci = this.lociFor(selection);
    if (!loci) return false;
    this.plugin.managers.camera.focusLoci(loci);
    return true;
  }

  focusPoint(point: { x: number; y: number; z: number; radius?: number }) {
    if (!this.plugin) return false;
    const { x, y, z, radius } = point;
    if (![x, y, z].every((value) => Number.isFinite(value))) return false;
    this.plugin.managers.camera.focusSphere(
      Sphere3D.create(Vec3.create(x, y, z), radius && radius > 0 ? radius : 5),
    );
    return true;
  }

  resetCamera() {
    this.assertMounted();
    this.plugin.managers.camera.reset();
  }

  setTheme(theme: 'light' | 'dark') {
    this.options.theme = theme === 'dark' ? 'dark' : 'light';
    if (this.plugin?.canvas3d) {
      this.plugin.canvas3d.setProps({ renderer: { backgroundColor: BACKGROUNDS[this.options.theme] } });
    }
  }

  resize() {
    if (!this.plugin) return;
    this.plugin.handleResize();
    this.plugin.canvas3d?.requestResize();
  }

  async captureImage() {
    this.assertMounted();
    const helper = this.plugin.helpers.viewportScreenshot;
    if (!helper) throw new Error('Mol* image export is unavailable');
    return helper.getImageDataUri();
  }

  onSelectionChanged(listener: SelectionListener) {
    this.selectionListeners.add(listener);
    return () => this.selectionListeners.delete(listener);
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.releaseResources();
  }

  private releaseResources() {
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.selectionSubscription?.unsubscribe();
    this.selectionSubscription = null;
    this.selectionListeners.clear();
    this.reactRoot?.unmount();
    this.reactRoot = null;
    this.plugin?.dispose();
    this.plugin = null;
    this.host?.replaceChildren();
    if (this.host && this.hostPosition != null) this.host.style.position = this.hostPosition;
    this.hostPosition = null;
    this.host = null;
  }

  private assertMounted() {
    if (!this.plugin || this.disposed) throw new Error('MolecularViewer is not mounted');
  }

  private enqueue<T>(work: () => Promise<T>): Promise<T> {
    const next = this.operation.then(work, work);
    this.operation = next.then(() => undefined, () => undefined);
    return next;
  }

  private hierarchy() {
    return this.plugin.managers.structure.hierarchy;
  }

  private components() {
    return this.hierarchy().currentComponentGroups.flat();
  }

  private async applyPresentation() {
    if (!this.plugin || !this.hierarchy().current.structures.length) return;
    const target = REPRESENTATIONS[this.representation];
    if (this.appliedRepresentation !== this.representation) {
      if (COMPOSED_REPRESENTATIONS.has(this.representation)) {
        const provider = this.plugin.builders.structure.representation.resolveProvider(target);
        if (!provider) throw new Error(`Unknown structure preset: ${target}`);
        await this.plugin.managers.structure.component.applyPreset(this.hierarchy().current.structures, provider, {
          theme: { globalName: COLORS[this.color] },
        });
      } else {
        const provider = this.plugin.representation.structure.registry.get(target);
        if (!provider) throw new Error(`Unknown structure representation: ${target}`);
        await this.plugin.dataTransaction(async () => {
          const existing = this.components();
          if (existing.length) await this.plugin.managers.structure.component.removeRepresentations(existing);
          for (const component of this.components()) {
            await this.plugin.builders.structure.representation.addRepresentation(component.cell, { type: provider });
          }
        }, { canUndo: 'Structure representation' });
      }
      this.appliedRepresentation = this.representation;
    }
    await this.applyColor();
    this.plugin.canvas3d?.commit(true);
  }

  private async applyColor() {
    if (!this.plugin) return;
    const components = this.components();
    if (!components.length) return;
    await this.plugin.managers.structure.component.updateRepresentationsTheme(components, { color: COLORS[this.color] });
  }

  // The residue matcher for one element, given the selection's numbering. It is a
  // pure predicate so the insertion-code semantics can be exercised directly.
  static matchesResidue(properties: {
    entity: string; authChain: string; labelChain: string; authSeqId: number; labelSeqId: number; insCode: string;
  }, selector: MolecularSelection): boolean {
    if (selector.entity && String(properties.entity) !== String(selector.entity)) return false;
    const auth = selector.numbering === 'auth_seq_id';
    const chain = auth ? properties.authChain : properties.labelChain;
    const residue = auth ? properties.authSeqId : properties.labelSeqId;
    if (selector.chain && String(chain) !== String(selector.chain)) return false;
    if (selector.residue != null && Number(residue) !== Number(selector.residue)) return false;
    // The insertion code is part of the residue identity (42A != 42) and is a
    // three-way constraint. UNSPECIFIED -- the caller never mentions it -- matches
    // any residue at this (chain, residue), with or without a code. An EXPLICIT
    // empty string matches only the bare residue (no code); a non-empty string
    // matches that exact code.
    if (selector.insertionCode == null) return true;
    return String(selector.insertionCode).trim() === String(properties.insCode || '').trim();
  }

  private lociFor(selection: MolecularSelection) {
    this.assertMounted();
    const structure = this.hierarchy().current.structures[0]?.cell?.obj?.data;
    if (!structure) return null;
    // A collection selects every listed residue in one combined loci; a single
    // residue selector is the one-element case of the same matcher.
    const selectors: MolecularSelection[] = selection.residues?.length ? selection.residues : [selection];
    const elements: Array<{ unit: any; indices: any }> = [];
    for (const unit of structure.units) {
      if (unit.kind !== 0) continue;
      const matches: number[] = [];
      const location = StructureElement.Location.create(structure, unit);
      for (let index = 0; index < unit.elements.length; index += 1) {
        location.element = unit.elements[index];
        const properties = {
          entity: String(StructureProperties.entity.id(location)),
          authChain: String(StructureProperties.chain.auth_asym_id(location) || ''),
          labelChain: String(StructureProperties.chain.label_asym_id(location) || ''),
          authSeqId: Number(StructureProperties.residue.auth_seq_id(location)),
          labelSeqId: Number(StructureProperties.residue.label_seq_id(location)),
          insCode: String(StructureProperties.residue.pdbx_PDB_ins_code(location) || '').trim(),
        };
        if (selectors.some((selector) => MolecularViewer.matchesResidue(properties, selector))) matches.push(index);
      }
      if (matches.length) elements.push({ unit, indices: OrderedSet.ofSortedArray(matches as any) });
    }
    return elements.length ? StructureElement.Loci(structure, elements) : null;
  }

  private selectedResidues(): SelectedResidue[] {
    if (!this.plugin) return [];
    const residues = new Map<string, SelectedResidue>();
    for (const structureRef of this.hierarchy().current.structures) {
      const structure = structureRef?.cell?.obj?.data;
      if (!structure) continue;
      const loci = this.plugin.managers.structure.selection.getLoci(structure);
      if (!loci?.elements) continue;
      StructureElement.Loci.forEachLocation(loci, (location: any) => {
        if (location.unit?.kind !== 0) return;
        const authChain = String(StructureProperties.chain.auth_asym_id(location) || '');
        const labelChain = String(StructureProperties.chain.label_asym_id(location) || '');
        const auth = Number(StructureProperties.residue.auth_seq_id(location));
        const label = Number(StructureProperties.residue.label_seq_id(location));
        const insCode = String(StructureProperties.residue.pdbx_PDB_ins_code(location) || '').trim();
        residues.set(`${labelChain}:${label}:${authChain}:${auth}:${insCode}`, {
          chain: labelChain,
          residue: label,
          auth_seq_id: auth,
          label_seq_id: label,
          // An absent/empty insertion code is omitted rather than published as an
          // empty string; both mean the bare residue number.
          ...(insCode ? { insertion_code: insCode } : {}),
        });
      });
    }
    return Array.from(residues.values());
  }

  private trajectoryInfo() {
    if (!this.plugin) return null;
    const state = this.plugin.state.data;
    const models = state.selectQ((query: any) => query.ofTransformer(StateTransforms.Model.ModelFromTrajectory));
    if (!models.length) return null;
    const model = models[0];
    const trajectory = state.cells.get(model.transform.parent);
    return {
      model,
      frame: Number(model.params.values.modelIndex || 0),
      frameCount: Number(trajectory?.obj?.data?.frameCount || 1),
    };
  }
}
