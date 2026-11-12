import { MeshBuilder } from 'molstar/lib/mol-geo/geometry/mesh/mesh-builder.js';
import { Mesh } from 'molstar/lib/mol-geo/geometry/mesh/mesh.js';
import { addBoundingBox } from 'molstar/lib/mol-geo/geometry/mesh/builder/box.js';
import { addSimpleCylinder } from 'molstar/lib/mol-geo/geometry/mesh/builder/cylinder.js';
import { addSphere } from 'molstar/lib/mol-geo/geometry/mesh/builder/sphere.js';
import { Shape } from 'molstar/lib/mol-model/shape.js';
import { ShapeRepresentation } from 'molstar/lib/mol-repr/shape/representation.js';
import { parseRecordedSpheres } from './sphere-geometry';
import { OrderedSet } from 'molstar/lib/mol-data/int.js';
import { Box3D, Sphere3D } from 'molstar/lib/mol-math/geometry.js';
import { Vec3 } from 'molstar/lib/mol-math/linear-algebra/3d/vec3.js';
import {
  StructureElement,
  StructureProperties,
} from 'molstar/lib/mol-model/structure.js';
import { StateTransforms } from 'molstar/lib/mol-plugin-state/transforms.js';
import { PluginUIContext } from 'molstar/lib/mol-plugin-ui/context.js';
import { Plugin } from 'molstar/lib/mol-plugin-ui/plugin.js';
import { DefaultPluginUISpec } from 'molstar/lib/mol-plugin-ui/spec.js';
import { PluginConfig } from 'molstar/lib/mol-plugin/config.js';
import { loadTrajectory as loadPluginTrajectory } from 'molstar/lib/extensions/plugin/loaders.js';
import { createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { PresetTrajectoryHierarchy } from 'molstar/lib/mol-plugin-state/builder/structure/hierarchy-preset.js';
import { ParamDefinition as PD } from 'molstar/lib/mol-util/param-definition.js';
import 'molstar/build/viewer/molstar.css';
import { t } from '../../app/i18n';
import { normalizePdbFrameDelimiters } from './pdb-frames';
import {
  ANGSTROM,
  atomKey,
  authoredResidue,
  SceneState,
  selectionSignature,
  structuralDigest,
  type AxisAlignedBox,
  type CenterOfMassOptions,
  type CoordinateUnits,
  type MolecularScene,
  type MolecularSceneEvent,
  type MolecularSelection,
  type SceneAtom,
  type SceneInitialization,
  type SceneMutationMeta,
  type SceneSelection,
  type SceneSnapshot,
  type SelectedResidue,
  type StructureSource,
  type XYZ,
} from './molecular-scene';
import { allAtoms as allSceneAtoms, selectionAtoms, selectionResidues } from './molstar-scene';

export { authoredResidue };
export type {
  AxisAlignedBox,
  CenterOfMassOptions,
  CoordinateUnits,
  MolecularScene,
  MolecularSceneEvent,
  MolecularSelection,
  SceneAtom,
  SceneInitialization,
  SceneMutationMeta,
  SceneSnapshot,
  SelectedResidue,
  StructureSource,
  XYZ,
};

const REPRESENTATIONS: Record<string, string> = {
  cartoon: 'cartoon',
  cartoon_ligand: 'polymer-and-ligand',
  sticks: 'ball-and-stick',
  points: 'spacefill',
  surface_ligand: 'molecular-surface',
};

const COMPOSED_REPRESENTATIONS = new Set(['cartoon_ligand']);
const COLORS: Record<string, string> = {
  chain: 'chain-id',
  rainbow: 'sequence-id',
  confidence: 'plddt-confidence',
  plddt: 'plddt-confidence',
};

const BACKGROUNDS = { light: 0xfcfdfb, dark: 0x111318 } as const;

export interface MolecularViewerOptions {
  /** This mode offers Mol*'s native panels. When false the viewer also hides
   *  Mol*'s own viewport affordance, so a reader never meets a control that
   *  cannot act on anything. */
  showControls?: boolean;
  /** Start with the native panel closed behind its disclosure. A mode whose task
   *  *is* the native panel (chain/residue selection) leaves this unset so the
   *  panel opens with the structure. */
  controlsCollapsed?: boolean;
  selectionEnabled?: boolean;
  theme?: 'light' | 'dark';
  /** Explicit overlay initialization. Omit it to start with no crosshair/box;
   *  the origin and the whole-structure centre of mass are never implicit. */
  sceneInitialization?: SceneInitialization;
}

type SelectionListener = (residues: SelectedResidue[]) => void;

// Mol*'s native panels are a single all-or-nothing disclosure. `showControls`
// gates every region, and the viewport-overlay button that owns that disclosure
// lives inside the *main* region, so the geometry the main region gets decides
// whether the button is reachable at all. A `controls.X === 'none'` entry
// removes one region's content while still reserving its column, which strands
// the button outside the reader's reach; leaving `controls.right` alone makes
// the region's presence follow `showControls` exactly. So the closed state is
// expressed by `showControls` (and, on mount, by the one update Mol*'s own
// button performs), `regionState.right` stays 'full', and a mode that offers no
// native panel removes the button rather than leaving a control that cannot act
// on anything. This viewer is the only control-state owner: it never writes a
// region state that contradicts a hidden panel.
function viewerSpec(options: MolecularViewerOptions) {
  const spec = DefaultPluginUISpec();
  const showControls = options.showControls !== false;
  spec.layout = {
    ...spec.layout,
    initial: {
      ...spec.layout?.initial,
      isExpanded: false,
      showControls: showControls && !options.controlsCollapsed,
      controlsDisplay: 'reactive',
      regionState: {
        left: 'hidden',
        top: options.selectionEnabled ? 'full' : 'hidden',
        right: 'full',
        bottom: 'hidden',
      },
    },
  };
  spec.config = [
    ...(spec.config || []),
    // One disclosure, one control surface. Mol*'s overlay button stays the
    // affordance wherever a native panel exists and is absent where it would be
    // a dead end. The floating buttons that would duplicate a capability the
    // Result workspace already owns are dropped: fullscreen and expand from the
    // workspace toolbar, and screenshot/state from `captureImage`.
    [PluginConfig.Viewport.ShowControls, showControls],
    [PluginConfig.Viewport.ShowSelectionMode, Boolean(options.selectionEnabled)],
    [PluginConfig.Viewport.ShowSettings, false],
    [PluginConfig.Viewport.ShowScreenshotControls, false],
    [PluginConfig.Viewport.ShowXR, 'never'],
    [PluginConfig.Viewport.ShowExpand, false],
    [PluginConfig.Viewport.ShowToggleFullscreen, false],
  ];
  spec.components = {
    ...spec.components,
    remoteState: 'none',
    controls: {
      ...spec.components?.controls,
      top: options.selectionEnabled ? spec.components?.controls?.top : 'none',
      left: 'none',
      bottom: 'none',
    },
  };
  return spec;
}

export class MolecularViewer implements MolecularScene {
  readonly units: CoordinateUnits = ANGSTROM;

  /** The mounted viewer is the scene adapter; there is no second instance. */
  get scene(): MolecularScene {
    return this;
  }
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
  private lastLegacySelectionSignature = '';
  private readonly sceneState = new SceneState();
  private sceneSubscription: (() => void) | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private disposed = false;
  private sphereRepresentation: any = null;
  private overlayRepresentation: any = null;
  private overlayGeneration = 0;
  private liveRegion: HTMLElement | null = null;
  private annotationSubscription: { unsubscribe(): void } | null = null;
  private annotation: HTMLElement | null = null;

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
    const spec = viewerSpec(options);
    const plugin = new PluginUIContext(spec);
    this.plugin = plugin;
    try {
      await plugin.init();
      this.reactRoot = createRoot(host);
      this.reactRoot.render(createElement(Plugin, { plugin }));
      try { await plugin.canvas3dInitialized; } catch { /* Mol* reports canvas failures through its UI. */ }
      plugin.selectionMode = Boolean(options.selectionEnabled && !options.controlsCollapsed);
      this.setTheme(options.theme || 'light');
      this.mountLiveRegion(host);
      this.sceneSubscription = this.sceneState.subscribe((event) => {
        if (event.type === 'crosshair' || event.type === 'box') this.renderOverlays();
        if (event.type !== 'frame') this.publishSceneStatus();
      });
      if (options.sceneInitialization) this.sceneState.initialize(options.sceneInitialization);
      this.selectionSubscription = plugin.managers.structure.selection.events.changed.subscribe(() => {
        this.handleViewerSelection();
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
      const digest = source.digest || await structuralDigest(source.data);
      this.removeSphereGeometry();
      await this.plugin.clear();
      // The old selection and overlays belong to the previous topology; they are
      // cleared here, never remapped onto the new chain/residue addresses.
      this.sceneState.topologyChanged({ digest, label: source.label || 'structure' });
      const raw = await this.plugin.builders.data.rawData({ data: source.data, label: source.label || 'structure' });
      const trajectory = await this.plugin.builders.structure.parseTrajectory(raw, source.format);
      await this.plugin.builders.structure.hierarchy.applyPreset(trajectory, 'default');
      this.appliedRepresentation = null;
      await this.applyPresentation();
      this.sceneState.refreshSelection(this.readSelection());
      this.lastLegacySelectionSignature = '';
      this.handleViewerSelection();
    });
  }

  loadTrajectory(source: {
    topology: string;
    topologyFormat?: 'pdb' | 'mmcif';
    coordinates: string | Uint8Array;
    coordinateFormat: string;
    label?: string;
  }) {
    return this.enqueue(async () => {
      this.assertMounted();
      // The topology is the identity: coordinate frames change the active frame,
      // not the digest or the revision.
      const digest = await structuralDigest(source.topology);
      this.removeSphereGeometry();
      await this.plugin.clear();
      this.sceneState.topologyChanged({ digest, label: source.label || 'trajectory' });
      if (source.coordinateFormat === 'pdb') {
        // Some runners delimit frames with ENDMDL alone (RFdiffusion's pX0 and
        // Xt-1 trajectories do). Mol* 5.12.0's PDB reader starts a model only at
        // a `MODEL ` record, so such a file collapses to one frame and the later
        // ENDMDL records would silently disappear. The delimiter is made explicit
        // before parsing; a file that already carries MODEL records is untouched.
        const text = typeof source.coordinates === 'string' ? source.coordinates : new TextDecoder().decode(source.coordinates);
        const normalized = normalizePdbFrameDelimiters(text);
        const raw = await this.plugin.builders.data.rawData({ data: normalized, label: source.label || 'trajectory' });
        const trajectory = await this.plugin.builders.structure.parseTrajectory(raw, 'pdb');
        await this.plugin.builders.structure.hierarchy.applyPreset(trajectory, 'default');
      } else {
        const loaded = await loadPluginTrajectory(this.plugin, {
          model: { kind: 'model-data', data: source.topology, format: source.topologyFormat || 'pdb' },
          modelLabel: 'Declared topology',
          coordinates: {
            kind: 'coordinates-data',
            data: source.coordinates,
            format: source.coordinateFormat,
          },
          coordinatesLabel: source.label || 'coordinates',
          // Coordinate frames can legitimately carry a zero box (BioEmu writes
          // one). Mol* then attaches an empty unit cell to every frame and its
          // default preset decorates the model with a hidden unit-cell shape,
          // whose instance grid is sized from NaN bounds and throws
          // `RangeError: Invalid typed array length` outside the load task. The
          // cell is hidden anyway, so leave it out of this preset.
          preset: { ...PresetTrajectoryHierarchy.default, params: () => ({ showUnitcell: PD.Boolean(false) }) },
        } as any);
        // Mol* resolves the preset to nothing when the coordinate stream fails to
        // parse; without this check the topology's own single-frame model would
        // be reported as a one-frame trajectory instead of an explicit error.
        if (!(loaded.preset as { model?: unknown } | undefined)?.model) throw new Error(t('results.trajectory.corrupted'));
      }
      this.appliedRepresentation = null;
      await this.applyPresentation();
      const info = this.trajectoryInfo();
      if (!info) throw new Error('Mol* did not create a trajectory');
      this.sceneState.setFrame(info.frame);
      this.sceneState.refreshSelection(this.readSelection());
      this.lastLegacySelectionSignature = '';
      this.handleViewerSelection();
      return { frame: info.frame, frameCount: info.frameCount };
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
      this.sceneState.setFrame(frame);
      this.sceneState.refreshSelection(this.readSelection());
      return { frame, frameCount: info.frameCount };
    });
  }

  clear() {
    return this.enqueue(async () => {
      this.assertMounted();
      this.removeSphereGeometry();
      await this.plugin.clear();
      this.sceneState.topologyChanged({ digest: '', label: '' });
      this.lastLegacySelectionSignature = '';
      this.handleViewerSelection();
      this.appliedRepresentation = null;
    });
  }

  setRepresentation(mode: string) {
    if (!REPRESENTATIONS[mode]) return Promise.reject(new Error(`Unknown representation: ${mode}`));
    this.representation = mode;
    return this.enqueue(async () => {
      const camera = this.plugin?.canvas3d?.camera; const snapshot = camera?.getSnapshot();
      await this.applyPresentation();
      if (snapshot) camera.setState(snapshot, 0);
    });
  }

  setColor(mode: string) {
    if (!COLORS[mode]) return Promise.reject(new Error(`Unknown color mode: ${mode}`));
    this.color = mode;
    return this.enqueue(() => this.applyColor());
  }

  select(selection: MolecularSelection, meta: SceneMutationMeta = {}) {
    this.sceneState.verifyTopology(meta.expectedTopology);
    this.sceneState.beginExternalMutation();
    try {
      let applied = true;
      if (Array.isArray(selection.residues) && !selection.residues.length) {
        this.plugin.managers.structure.selection.clear();
      } else {
        const loci = this.lociFor(selection);
        if (!loci) applied = false;
        // One combined loci, one 'set': a multi-residue selection replaces the
        // previous selection in a single operation rather than accumulating calls.
        else this.plugin.managers.structure.selection.fromLoci('set', loci, false);
      }
      if (applied) {
        this.sceneState.selectFromForm(this.readSelection(), meta);
        // The form's own mutation is suppressed as an extra scene event, but its
        // residue listeners still see the normalized selection exactly once.
        this.handleViewerSelection();
      }
      return applied;
    } finally {
      this.sceneState.endExternalMutation();
    }
  }

  clearSelection(meta: SceneMutationMeta = {}): void {
    this.select({ residues: [] }, meta);
  }

  setHighlight(selection: MolecularSelection, meta: SceneMutationMeta = {}): boolean {
    this.sceneState.verifyTopology(meta.expectedTopology);
    if (Array.isArray(selection.residues) && !selection.residues.length) {
      this.clearHighlight();
      return true;
    }
    const loci = this.lociFor(selection);
    if (!loci) return false;
    this.plugin.managers.interactivity.lociHighlights.highlight({ loci }, false);
    return true;
  }

  clearHighlight(): void {
    this.plugin?.managers.interactivity.lociHighlights.clearHighlights();
  }

  focus(selection: MolecularSelection, meta: SceneMutationMeta = {}) {
    this.sceneState.verifyTopology(meta.expectedTopology);
    if (selection && selection.focusPoint) return this.focusPoint(selection.focusPoint);
    const loci = this.lociFor(selection);
    if (!loci) return false;
    this.plugin.managers.camera.focusLoci(loci);
    return true;
  }

  focusPoint(point: XYZ & { radius?: number }) {
    if (!this.plugin) return false;
    const { x, y, z, radius } = point;
    if (![x, y, z].every((value) => Number.isFinite(value))) return false;
    this.plugin.managers.camera.focusSphere(
      Sphere3D.create(Vec3.create(x, y, z), radius && radius > 0 ? radius : 5),
    );
    return true;
  }

  // -- MolecularScene: read/subscribe, overlays and derived geometry ---------

  snapshot(): SceneSnapshot {
    return this.sceneState.snapshot();
  }

  subscribe(listener: (event: MolecularSceneEvent) => void): () => void {
    return this.sceneState.subscribe(listener);
  }

  lastEvent(): MolecularSceneEvent | null {
    return this.sceneState.lastEvent();
  }

  getCrosshair(): XYZ | null {
    return this.sceneState.getCrosshair();
  }

  setCrosshair(point: XYZ | null, meta: SceneMutationMeta = {}): XYZ | null {
    const next = this.sceneState.setCrosshair(point, meta);
    this.renderOverlays();
    this.publishSceneStatus();
    return next;
  }

  getBox(): AxisAlignedBox | null {
    return this.sceneState.getBox();
  }

  setBox(box: AxisAlignedBox | null, meta: SceneMutationMeta = {}): AxisAlignedBox | null {
    const next = this.sceneState.setBox(box, meta);
    this.renderOverlays();
    this.publishSceneStatus();
    return next;
  }

  centroid(atoms?: readonly SceneAtom[]): XYZ {
    return this.sceneState.centroid(atoms);
  }

  centerOfMass(options: CenterOfMassOptions, atoms?: readonly SceneAtom[]): XYZ {
    return this.sceneState.centerOfMass(options, atoms);
  }

  boundingBox(atoms?: readonly SceneAtom[]): AxisAlignedBox {
    return this.sceneState.boundingBox(atoms);
  }

  allAtoms(): SceneAtom[] {
    const structure = this.plugin?.managers?.structure?.hierarchy?.current?.structures?.[0]?.cell?.obj?.data;
    return structure ? allSceneAtoms(structure) : [];
  }

  pickAtoms(): Promise<SceneAtom[]> {
    return this.sceneState.pickAtoms();
  }

  resetCamera() {
    this.assertMounted();
    this.plugin.managers.camera.reset();
  }

  setTheme(theme: 'light' | 'dark') {
    this.options.theme = theme === 'dark' ? 'dark' : 'light';
    if (this.plugin?.canvas3d) {
      this.plugin.canvas3d.setProps({ renderer: { backgroundColor: BACKGROUNDS[this.options.theme], selectColor: 0xa6406c }, marking: { selectEdgeColor: 0xa6406c } });
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

  private removeSphereGeometry(): void {
    if (!this.sphereRepresentation) return;
    this.plugin?.canvas3d?.remove(this.sphereRepresentation); this.sphereRepresentation.destroy(); this.sphereRepresentation = null;
  }

  setSphereGeometry(source: string | null): Promise<void> {
    return this.enqueue(async () => {
      this.removeSphereGeometry(); if (source == null) return;
      this.assertMounted(); const spheres = parseRecordedSpheres(source);
      const mesh = MeshBuilder.createState(2048, 2048);
      spheres.forEach((sphere, index) => { mesh.currentGroup = index; addSphere(mesh, Vec3.create(...sphere.center), sphere.radius, 2); });
      const shape = Shape.create('Recorded alpha spheres', spheres, MeshBuilder.getMesh(mesh), () => 0xb5964c as any, () => 1, index => `Alpha sphere ${index + 1} · radius ${spheres[index]!.radius} Å`);
      const representation = ShapeRepresentation(() => shape, Mesh.Utils);
      try { await representation.createOrUpdate({ alpha: .23, doubleSided: true }, spheres).run(); this.plugin.canvas3d.add(representation); this.sphereRepresentation = representation; }
      catch (error) { representation.destroy(); throw error; }
    });
  }

  annotate(annotation: { point: { x: number; y: number; z: number }; label: string } | null): void {
    this.annotationSubscription?.unsubscribe(); this.annotationSubscription = null; this.annotation?.remove(); this.annotation = null;
    if (!annotation || !this.host || !this.plugin?.canvas3d || !Object.values(annotation.point).every(Number.isFinite)) return;
    const marker = document.createElement('div'); marker.className = 'molecular-annotation'; const label = document.createElement('span'); label.textContent = annotation.label; marker.append(label); this.host.append(marker); this.annotation = marker;
    const update = () => {
      const camera = this.plugin.canvas3d.camera, point = Vec3(); camera.project(point, Vec3.create(annotation.point.x, annotation.point.y, annotation.point.z));
      const x = (point[0]! - camera.viewport.x) * this.host!.clientWidth / camera.viewport.width;
      const y = (camera.viewport.height - point[1]! + camera.viewport.y) * this.host!.clientHeight / camera.viewport.height;
      marker.style.left = `${x}px`; marker.style.top = `${y}px`; marker.hidden = point[2]! < 0 || point[2]! > 1 || x < 0 || x > this.host!.clientWidth || y < 0 || y > this.host!.clientHeight;
    };
    this.annotationSubscription = this.plugin.canvas3d.didDraw.subscribe(update); update();
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
    this.removeSphereGeometry();
    this.removeOverlayRepresentation();
    this.annotationSubscription?.unsubscribe(); this.annotationSubscription = null; this.annotation?.remove(); this.annotation = null;
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.selectionSubscription?.unsubscribe();
    this.selectionSubscription = null;
    this.sceneSubscription?.();
    this.sceneSubscription = null;
    this.selectionListeners.clear();
    this.liveRegion?.remove();
    this.liveRegion = null;
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
    const target = REPRESENTATIONS[this.representation] ?? this.representation;
    if (this.appliedRepresentation !== this.representation) {
      if (COMPOSED_REPRESENTATIONS.has(this.representation)) {
        const provider = this.plugin.builders.structure.representation.resolveProvider(target);
        if (!provider) throw new Error(t('results.structure.presetUnavailable', { target }));
        await this.plugin.managers.structure.component.applyPreset(this.hierarchy().current.structures, provider, {
          theme: { globalName: COLORS[this.color] },
        });
      } else {
        const provider = this.plugin.representation.structure.registry.get(target);
        if (!provider) throw new Error(t('results.structure.representationUnavailable', { target }));
        await this.plugin.dataTransaction(async () => {
          const existing = this.components();
          if (existing.length) await this.plugin.managers.structure.component.removeRepresentations(existing);
          for (const component of this.components()) {
            await this.plugin.builders.structure.representation.addRepresentation(component.cell, { type: provider, ...(this.representation === 'points' ? { size: 'uniform', sizeParams: { value: 0.25 } } : {}) });
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

  /** The current Mol* selection, read once into the scene's stable vocabulary. */
  private readSelection(): SceneSelection {
    const atoms = new Map<string, SceneAtom>();
    const residues = new Map<string, SelectedResidue>();
    // The scene reads whatever hierarchy Mol* has published; a minimal embed
    // (or a test double) without one reports an empty selection.
    const structures = this.plugin?.managers?.structure?.hierarchy?.current?.structures;
    if (!Array.isArray(structures)) return { atoms: [], residues: [] };
    for (const structureRef of structures) {
      const structure = structureRef?.cell?.obj?.data;
      if (!structure) continue;
      const loci = this.plugin.managers.structure.selection.getLoci(structure);
      if (!loci?.elements) continue;
      for (const atom of selectionAtoms(loci)) atoms.set(atomKey(atom.identity), atom);
      for (const residue of selectionResidues(loci)) {
        residues.set(
          `${residue.chain}:${residue.residue}:${residue.auth_chain}:${residue.auth_seq_id}:${residue.insertion_code || ''}`,
          residue,
        );
      }
    }
    return { atoms: Array.from(atoms.values()), residues: Array.from(residues.values()) };
  }

  /**
   * Mol* reports a selection change. The echo of the form's own mutation is
   * consumed by `SceneState`; only a genuine viewer-origin change reaches the
   * legacy residue listeners.
   */
  private handleViewerSelection(): void {
    if (!this.plugin) return;
    const selection = this.readSelection();
    this.sceneState.adoptViewerSelection(selection);
    // Legacy residue listeners feed the Create Task form. They receive each
    // distinct selection once, including a normalized form-originated one, so a
    // parameter edit and a viewer click converge on the same workspace state.
    const signature = selectionSignature(selection.residues, selection.atoms);
    if (signature !== this.lastLegacySelectionSignature) {
      this.lastLegacySelectionSignature = signature;
      this.selectionListeners.forEach(listener => listener(selection.residues));
    }
    this.publishSceneStatus();
  }

  private mountLiveRegion(host: HTMLElement): void {
    const region = document.createElement('p');
    region.className = 'structure-scene-status sr-only';
    region.setAttribute('role', 'status');
    region.setAttribute('aria-live', 'polite');
    host.append(region);
    this.liveRegion = region;
  }

  /**
   * Screen-reader summary of the scene. Selections are named by the authored
   * residue count; a crosshair is announced in Angstrom, never as a bare tuple.
   */
  private publishSceneStatus(): void {
    if (!this.liveRegion) return;
    const residues = this.sceneState.snapshot().selectedResidues.length;
    const crosshair = this.sceneState.getCrosshair();
    const parts: string[] = [];
    if (residues) parts.push(t('results.structure.selectionStatus', { count: residues }));
    if (crosshair) {
      parts.push(t('results.structure.crosshairStatus', {
        x: crosshair.x.toFixed(2), y: crosshair.y.toFixed(2), z: crosshair.z.toFixed(2),
      }));
    }
    this.liveRegion.textContent = parts.join(' ');
  }

  private removeOverlayRepresentation(): void {
    this.overlayGeneration += 1;
    if (!this.overlayRepresentation) return;
    this.plugin?.canvas3d?.remove(this.overlayRepresentation);
    this.overlayRepresentation.destroy();
    this.overlayRepresentation = null;
  }

  /**
   * Draw the crosshair and axis-aligned box as a shape overlay.
   *
   * The overlay is built from copies of the scene's numeric state and added to
   * the canvas beside the structure; no structure or trajectory array is read
   * into a mutable buffer or written back.
   */
  private renderOverlays(): void {
    this.removeOverlayRepresentation();
    if (!this.plugin?.canvas3d) return;
    const crosshair = this.sceneState.getCrosshair();
    const box = this.sceneState.getBox();
    if (!crosshair && !box) { this.plugin.canvas3d.commit(true); return; }
    const generation = this.overlayGeneration;
    const mesh = MeshBuilder.createState(512, 512);
    const data: unknown[] = [];
    let group = 0;
    if (box) {
      mesh.currentGroup = group;
      data.push({ kind: 'box', box });
      group += 1;
      const half = { x: box.lengths.x / 2, y: box.lengths.y / 2, z: box.lengths.z / 2 };
      addBoundingBox(
        mesh,
        Box3D.create(
          Vec3.create(box.center.x - half.x, box.center.y - half.y, box.center.z - half.z),
          Vec3.create(box.center.x + half.x, box.center.y + half.y, box.center.z + half.z),
        ),
        0.06, 1, 8,
      );
    }
    if (crosshair) {
      mesh.currentGroup = group;
      data.push({ kind: 'crosshair', crosshair });
      const size = 0.85;
      const props = { radiusTop: 0.035, radiusBottom: 0.035, radialSegments: 8 };
      addSimpleCylinder(mesh, Vec3.create(crosshair.x - size, crosshair.y, crosshair.z), Vec3.create(crosshair.x + size, crosshair.y, crosshair.z), props);
      addSimpleCylinder(mesh, Vec3.create(crosshair.x, crosshair.y - size, crosshair.z), Vec3.create(crosshair.x, crosshair.y + size, crosshair.z), props);
      addSimpleCylinder(mesh, Vec3.create(crosshair.x, crosshair.y, crosshair.z - size), Vec3.create(crosshair.x, crosshair.y, crosshair.z + size), props);
      addSphere(mesh, Vec3.create(crosshair.x, crosshair.y, crosshair.z), 0.08, 1);
    }
    const shape = Shape.create('Molecular overlays', data, MeshBuilder.getMesh(mesh), () => 0x2f6f8f as any, () => 1, () => 'Molecular overlay');
    const representation = ShapeRepresentation(() => shape, Mesh.Utils);
    representation.createOrUpdate({ alpha: 1, doubleSided: true }, data).run().then(() => {
      if (generation !== this.overlayGeneration || !this.plugin?.canvas3d) { representation.destroy(); return; }
      this.plugin.canvas3d.add(representation);
      this.overlayRepresentation = representation;
      this.plugin.canvas3d.commit(true);
    }, () => representation.destroy());
  }

  private trajectoryInfo() {
    if (!this.plugin) return null;
    const state = this.plugin.state.data;
    let best: { model: any; frameCount: number } | null = null;
    for (const model of state.selectQ((query: any) => query.ofTransformer(StateTransforms.Model.ModelFromTrajectory))) {
      const trajectory = state.cells.get(model.transform.parent);
      const frames = Number(trajectory?.obj?.data?.frameCount || 0);
      if (!best || frames > best.frameCount) best = { model, frameCount: frames };
    }
    if (!best || best.frameCount < 1) return null;
    return {
      model: best.model,
      frame: Number(best.model.params.values.modelIndex || 0),
      frameCount: best.frameCount,
    };
  }
}
