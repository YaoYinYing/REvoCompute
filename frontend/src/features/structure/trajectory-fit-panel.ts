/*
 * The trajectory Result Workspace's preview fitting controls.
 *
 * This panel owns presentation state only: the fit atom subset chosen through the
 * shared typed scene, the reference frame, an explicit center/fit mode, the
 * per-frame transform results, and the honest PDB export. It never mutates the
 * downloaded bytes or the published artifact; the reversible display transform is
 * a Mol* conformation decorator applied by the viewer.
 *
 * Every RMSD shown here is a preview metric on the fit selection. It is not
 * simulation dynamics, stability, or a published scientific result.
 */
import { resultFileName, type ResultFile } from '../../api/result-types';
import { t } from '../../app/i18n';
import { StructureController } from '../results/molecular/structure-controller';
import {
  selectionSignature,
  type SceneAtom,
  type SceneSnapshot,
} from './molecular-scene';
import {
  pbcPolicyOf,
  positionsSpanPeriodicBoundary,
  validateFitSelection,
  fromColumnMajorMatrix,
  TrajectoryFitError,
  type FitMode,
  type PeriodicBox,
  type PbcPolicy,
} from './trajectory-fit';
import { TrajectoryFitClient, type FitWorkerFactory } from './trajectory-fit-client';
import { assertFitJobSize, assertUniqueAtomIndices } from './trajectory-fit-protocol';
import { PdbExportError, writePreviewMetadata, writePreviewPdb } from './preview-pdb';

export interface TrajectoryFitSource {
  topology: ResultFile;
  coordinates: ResultFile;
  coordinateFormat: string;
  topologyFormat: string;
}

export interface TrajectoryFitPanelOptions {
  controller: StructureController;
  taskId: string;
  /** The artifact pair currently on screen; changes when a design is selected. */
  source(): TrajectoryFitSource | null;
  /** Test seam: production defaults to a module Worker. */
  createClient?: () => TrajectoryFitClient;
  /** Test seam: production creates an object URL and clicks an anchor. */
  download?: (name: string, text: string, mediaType: string) => void;
}

export interface TrajectoryFitPanel {
  readonly element: HTMLElement;
  /** Publish the displayed frame and keep the preview transform in step. */
  frameDisplayed(frame: number, frameCount: number): Promise<void>;
  /** A new source artifact is being mounted; drop every cached transform. */
  reset(): void;
  destroy(): void;
}

interface PbcState {
  policy: PbcPolicy;
  spanning: boolean;
  box: PeriodicBox | null;
}

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function button(label: string, className = 'result-button result-button-small'): HTMLButtonElement {
  const node = element('button', className) as HTMLButtonElement;
  node.type = 'button';
  node.textContent = label;
  node.disabled = true;
  return node;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function defaultDownload(name: string, text: string, mediaType: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: mediaType }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.rel = 'noopener';
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function createTrajectoryFitPanel(options: TrajectoryFitPanelOptions): TrajectoryFitPanel {
  const { controller } = options;
  const client = (options.createClient ?? (() => new TrajectoryFitClient()))();
  const download = options.download ?? defaultDownload;

  let frameCount = 0;
  let currentFrame = 0;
  let referenceFrame = 0;
  let mode: FitMode = 'fit';
  let previewActive = false;
  let transforms: Float64Array | null = null;
  let rmsd: Float64Array | null = null;
  let rejected = new Set<number>();
  let fitAtomCount = 0;
  let fitSignature = '';
  let fitSource: { revision: number; digest: string } | null = null;
  let pbc: PbcState = { policy: 'none', spanning: false, box: null };
  let activeJob: AbortController | null = null;
  let jobGeneration = 0;
  let sceneUnsubscribe: (() => void) | null = null;
  let destroyed = false;

  const panel = element('div', 'trajectory-fit');
  const scopeLabel = element('label', 'structure-tool-field', t('results.trajectory.fitAtoms'));
  const scope = element('select', 'trajectory-fit-scope') as HTMLSelectElement;
  const wholeOption = element('option', undefined, t('results.trajectory.fitWholeFrame'));
  wholeOption.value = 'whole';
  const selectionOption = element('option', undefined, t('results.trajectory.fitSelection', { count: 0 }));
  selectionOption.value = 'selection';
  selectionOption.disabled = true;
  scope.append(wholeOption, selectionOption);
  scope.value = 'whole';
  scope.disabled = true;
  scopeLabel.append(scope);

  const selectButton = button(t('results.trajectory.selectFitAtoms'), 'result-button result-button-small');
  selectButton.setAttribute('aria-pressed', 'false');
  const referenceLabel = element('label', 'structure-tool-field', t('results.trajectory.referenceFrame'));
  const referenceInput = element('input', 'trajectory-fit-reference') as HTMLInputElement;
  referenceInput.type = 'number';
  referenceInput.min = '1';
  referenceInput.max = '1';
  referenceInput.step = '1';
  referenceInput.value = '1';
  referenceInput.disabled = true;
  referenceLabel.append(referenceInput);
  const useCurrent = button(t('results.trajectory.useCurrentFrame'));
  const centerButton = button(t('results.trajectory.centerOnly'));
  const fitButton = button(t('results.trajectory.fitAndPreview'));
  const resetButton = button(t('results.trajectory.resetPreview'));
  const exportButton = button(t('results.trajectory.exportAlignedFrame'));
  const status = element('p', 'result-note trajectory-fit-status');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  panel.append(
    scopeLabel, selectButton, referenceLabel, useCurrent,
    centerButton, fitButton, resetButton, exportButton, status,
  );

  const publish = (text: string): void => {
    if (!destroyed) status.textContent = text;
  };
  const setBusy = (busy: boolean): void => {
    const supported = controller.supportsTrajectoryFitting();
    scope.disabled = busy || !supported;
    selectButton.disabled = busy || !supported;
    referenceInput.disabled = busy || !supported || frameCount < 2;
    useCurrent.disabled = busy || !supported || frameCount < 2;
    centerButton.disabled = busy || !supported;
    fitButton.disabled = busy || !supported;
    resetButton.disabled = busy || !previewActive;
    exportButton.disabled = busy || !previewActive;
  };

  const sourceMatches = (): boolean => {
    const snapshot = controller.scene()?.snapshot();
    if (!fitSource || !snapshot) return false;
    return snapshot.topologyRevision === fitSource.revision && snapshot.topologyDigest === fitSource.digest;
  };

  const clearPreview = (message?: string): void => {
    previewActive = false;
    transforms = null;
    rmsd = null;
    rejected = new Set();
    fitSource = null;
    void controller.applyPreviewTransform(null).catch(() => undefined);
    setBusy(false);
    publish(message ?? t('results.trajectory.previewCleared'));
  };

  const reset = (): void => {
    activeJob?.abort();
    activeJob = null;
    jobGeneration += 1;
    frameCount = 0;
    currentFrame = 0;
    referenceFrame = 0;
    referenceInput.value = '1';
    referenceInput.max = '1';
    previewActive = false;
    transforms = null;
    rmsd = null;
    rejected = new Set();
    fitAtomCount = 0;
    fitSignature = '';
    fitSource = null;
    pbc = { policy: 'none', spanning: false, box: null };
    // A different source must never inherit the previous source's display
    // transform; the decorator is cleared as well as the cached matrices.
    void controller.applyPreviewTransform(null).catch(() => undefined);
    setBusy(false);
    publish('');
  };

  const updateSelectionOption = (): void => {
    const count = controller.scene()?.snapshot().selectedAtoms.length ?? 0;
    selectionOption.textContent = t('results.trajectory.fitSelection', { count });
    selectionOption.disabled = count < 3;
    if (count < 3 && scope.value === 'selection') scope.value = 'whole';
  };

  const attachScene = (): void => {
    if (sceneUnsubscribe || !controller.supportsTrajectoryFitting()) return;
    sceneUnsubscribe = controller.subscribeScene((event) => {
      if (event.type === 'selection') {
        updateSelectionOption();
        if (previewActive) clearPreview(t('results.trajectory.fitSelectionChanged'));
      }
      if (event.type === 'topology') reset();
    });
    updateSelectionOption();
  };

  const applyFrame = async (frame: number): Promise<void> => {
    if (!previewActive || !transforms) return;
    if (!sourceMatches()) {
      reset();
      publish(t('results.trajectory.fitSourceChanged'));
      return;
    }
    if (rejected.has(frame)) {
      await controller.applyPreviewTransform(null).catch(() => undefined);
      publish(t('results.trajectory.fitFrameRejected', { frame: frame + 1 }));
      return;
    }
    await controller.applyPreviewTransform(transforms.subarray(frame * 16, frame * 16 + 16)).catch((error) => {
      publish(messageOf(error));
    });
    const value = rmsd?.[frame];
    publish(Number.isFinite(value)
      ? t('results.trajectory.fitApplied', {
        rmsd: Number(value).toFixed(3),
        atoms: fitAtomCount,
        reference: referenceFrame + 1,
        pbc: pbc.policy === 'periodic'
          ? (pbc.spanning ? t('results.trajectory.fitPbcSpanning') : t('results.trajectory.fitPbcDeclared'))
          : t('results.trajectory.fitPbcNone'),
      })
      : t('results.trajectory.fitAppliedNoRmsd', { atoms: fitAtomCount, reference: referenceFrame + 1 }));
  };

  const fit = async (selectedMode: FitMode): Promise<void> => {
    if (destroyed) return;
    if (!controller.supportsTrajectoryFitting()) {
      publish(t('results.trajectory.fittingUnavailable'));
      return;
    }
    activeJob?.abort();
    const job = new AbortController();
    activeJob = job;
    const generation = ++jobGeneration;
    previewActive = false;
    transforms = null;
    rmsd = null;
    rejected = new Set();
    fitSource = null;
    await controller.applyPreviewTransform(null).catch(() => undefined);
    setBusy(true);

    try {
      const snapshot: SceneSnapshot | null = controller.scene()?.snapshot() ?? null;
      const atoms = scope.value === 'selection'
        ? (snapshot?.selectedAtoms ?? [])
        : controller.allAtoms();
      if (atoms.length < 3) {
        publish(t('results.trajectory.fitSelectionTooSmall'));
        return;
      }
      const indices = uniqueIndices(atoms);
      if (indices.length !== atoms.length) throw new TrajectoryFitError('The fit selection addresses the same atom more than once.');
      assertUniqueAtomIndices(indices);
      assertFitJobSize(indices.length, frameCount);
      const reference = controller.readTrajectoryFrame(referenceFrame, indices);
      validateFitSelection(reference);
      // The periodic warning describes the displayed frame's whole coordinate
      // set, not just the fit subset: a wrapped topology can break a rigid fit
      // even when the selected atoms look compact. The whole-frame read is
      // bounded; a very large topology falls back to the fit subset.
      const allIndices = uniqueIndices(controller.allAtoms());
      const pbcIndices = allIndices.length <= 20000 ? allIndices : indices;
      const allCoordinates = controller.readTrajectoryFrame(referenceFrame, pbcIndices);
      const box = controller.trajectoryFrameCell(referenceFrame);
      const policy = pbcPolicyOf(box);
      pbc = {
        policy,
        spanning: box ? positionsSpanPeriodicBoundary(allCoordinates, box) : false,
        box,
      };
      publish(t('results.trajectory.fitWorking'));
      const result = await client.run({
        mode: selectedMode,
        reference,
        atomCount: indices.length,
        frameCount,
        readFrame: (frame) => controller.readTrajectoryFrame(frame, indices),
        signal: job.signal,
        onProgress: (completed, total) => {
          if (generation === jobGeneration) publish(t('results.trajectory.fitProgress', { completed, total }));
        },
      });
      if (generation !== jobGeneration || destroyed) return;
      transforms = result.transforms;
      rmsd = result.rmsd;
      rejected = new Set(result.rejectedFrames);
      fitAtomCount = indices.length;
      fitSignature = selectionSignature([], atoms) || indices.join(',');
      fitSource = snapshot ? { revision: snapshot.topologyRevision, digest: snapshot.topologyDigest } : null;
      mode = selectedMode;
      previewActive = true;
      setBusy(false);
      await applyFrame(currentFrame);
    } catch (error) {
      if (isAbort(error) || generation !== jobGeneration || destroyed) return;
      publish(messageOf(error));
    } finally {
      if (activeJob === job) {
        activeJob = null;
        if (!destroyed) setBusy(false);
      }
    }
  };

  const exportFrame = (): void => {
    if (!previewActive || !transforms || !fitSource) {
      publish(t('results.trajectory.exportNeedsFit'));
      return;
    }
    if (!sourceMatches()) {
      reset();
      publish(t('results.trajectory.fitSourceChanged'));
      return;
    }
    if (rejected.has(currentFrame)) {
      publish(t('results.trajectory.fitFrameRejected', { frame: currentFrame + 1 }));
      return;
    }
    const transform = fromColumnMajorMatrix(transforms.subarray(currentFrame * 16, currentFrame * 16 + 16));
    const atoms = controller.allAtoms();
    if (!atoms.length) {
      publish(t('results.trajectory.exportEmpty'));
      return;
    }
    const source = options.source();
    if (!source) {
      publish(t('results.trajectory.exportEmpty'));
      return;
    }
    const indices = atoms.map((atom) => atom.identity.index);
    if (new Set(indices).size !== indices.length) {
      publish(t('results.trajectory.exportFailed'));
      return;
    }
    assertUniqueAtomIndices(indices);
    // Export reads the source frame rather than the displayed hierarchy, so a
    // preview decorator can never be mistaken for the artifact's coordinates.
    const raw = controller.readTrajectoryFrame(currentFrame, indices);
    const exportAtoms: SceneAtom[] = atoms.map((atom, index) => ({
      identity: atom.identity,
      element: atom.element,
      position: { x: raw[index * 3]!, y: raw[index * 3 + 1]!, z: raw[index * 3 + 2]! },
    }));
    const stem = (resultFileName(source.coordinates).split('/').pop() || 'trajectory').replace(/\.[^.]*$/, '');
    const frameLabel = `frame-${currentFrame + 1}`;
    let pdb: string;
    let metadata: string;
    try {
      pdb = writePreviewPdb(exportAtoms, transform);
      metadata = writePreviewMetadata({
        frame: currentFrame,
        frameCount,
        referenceFrame,
        mode,
        fitAtomCount,
        selectionSignature: fitSignature,
        rmsd: rmsd?.[currentFrame] ?? null,
        pbcPolicy: pbc.policy,
        pbcSpanning: pbc.spanning,
        box: pbc.box,
        source: {
          taskId: options.taskId,
          topologyPath: source.topology.path,
          topologySha256: digestOf(source.topology),
          topologyFormat: source.topologyFormat,
          coordinatesPath: source.coordinates.path,
          coordinatesSha256: digestOf(source.coordinates),
          coordinateFormat: source.coordinateFormat,
        },
      }, transform);
    } catch (error) {
      publish(error instanceof PdbExportError ? error.message : t('results.trajectory.exportFailed'));
      return;
    }
    download(`${stem}.${frameLabel}.preview.pdb`, pdb, 'chemical/x-pdb');
    download(`${stem}.${frameLabel}.preview.metadata.json`, metadata, 'application/json');
    publish(t('results.trajectory.exported', { frame: currentFrame + 1, atoms: exportAtoms.length }));
  };

  const selectAtoms = (): void => {
    const enabled = selectButton.getAttribute('aria-pressed') !== 'true';
    selectButton.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    selectButton.textContent = enabled ? t('results.trajectory.selectFitAtomsOn') : t('results.trajectory.selectFitAtoms');
    controller.setSelectionMode(enabled);
    if (enabled) publish(t('results.trajectory.selectFitAtomsHint'));
  };

  scope.addEventListener('change', () => {
    if (previewActive) clearPreview(t('results.trajectory.fitSelectionChanged'));
  });
  selectButton.addEventListener('click', selectAtoms);
  referenceInput.addEventListener('change', () => {
    const requested = Number(referenceInput.value) - 1;
    referenceFrame = Number.isFinite(requested) ? Math.max(0, Math.min(frameCount - 1, Math.trunc(requested))) : 0;
    referenceInput.value = String(referenceFrame + 1);
    if (previewActive) clearPreview(t('results.trajectory.fitReferenceChanged'));
  });
  useCurrent.addEventListener('click', () => {
    referenceFrame = currentFrame;
    referenceInput.value = String(referenceFrame + 1);
    if (previewActive) clearPreview(t('results.trajectory.fitReferenceChanged'));
  });
  centerButton.addEventListener('click', () => void fit('center'));
  fitButton.addEventListener('click', () => void fit('fit'));
  resetButton.addEventListener('click', () => clearPreview());
  exportButton.addEventListener('click', exportFrame);

  return {
    element: panel,
    async frameDisplayed(frame: number, total: number): Promise<void> {
      if (destroyed) return;
      if (total !== frameCount) {
        reset();
        frameCount = total;
        referenceInput.max = String(Math.max(1, total));
        referenceInput.disabled = total < 2;
      }
      currentFrame = Math.max(0, Math.min(total - 1, Math.trunc(frame)));
      attachScene();
      setBusy(false);
      await applyFrame(currentFrame);
    },
    reset,
    destroy(): void {
      destroyed = true;
      activeJob?.abort();
      activeJob = null;
      jobGeneration += 1;
      sceneUnsubscribe?.();
      sceneUnsubscribe = null;
      client.dispose();
    },
  };
}

/** Sorted unique viewer element indices; duplicates are rejected by the caller. */
function uniqueIndices(atoms: readonly SceneAtom[]): number[] {
  return [...new Set(atoms.map((atom) => atom.identity.index))].sort((left, right) => left - right);
}

/** The manifest digest when the source exposes one; never invented. */
function digestOf(file: ResultFile): string | null {
  return 'sha256' in file && typeof file.sha256 === 'string' ? file.sha256 : null;
}
