/*
 * Server-declared `trajectory` ResultView rendering: one Mol* stage fed by every
 * declared source (a topology plus binary coordinate frames), with frame count
 * and previous/next/scrub controls. The frame axis is labelled with the mapping's
 * own `frame_unit`; it never invents physical time.
 */
import type { ResultFile, ResultView } from '../../api/result-types';
import { resultFileName } from '../../api/result-types';
import { t } from '../../app/i18n';
import { StructureController } from './molecular/structure-controller';
import type { MolecularViewerFactory, TrajectoryInfo } from './molecular/viewer-contract';
import type { ResolvedViewSources, ViewRenderer } from './renderer-registry';

export interface TrajectoryMapping {
  coordinate_format?: string;
  frame_unit?: string;
  timestep?: number;
  association?: string;
}

/** How long one frame stays on screen while playback runs. */
const PLAYBACK_INTERVAL_MS = 200;

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

/** A published path's basename without its extension, as the server's stem-prefix rule reads it. */
function stemOf(file: ResultFile): string {
  const name = resultFileName(file).split('/').pop() || '';
  return name.replace(/\.[^.]*$/, '');
}

/**
 * The coordinate artifact declared for one topology.
 *
 * `stem-prefix` means the coordinate's own name starts with the topology's stem, so
 * the pair is read from the declaration; positional pairing would show one design's
 * topology over another design's frames when a design's trajectory was not written.
 */
export function associatedCoordinates(
  topology: ResultFile,
  coordinates: ResultFile[],
  association: string | undefined,
): ResultFile | undefined {
  if (association !== 'stem-prefix') return coordinates[0];
  const stem = stemOf(topology);
  return coordinates.find((file) => (resultFileName(file).split('/').pop() || '').startsWith(`${stem}_`));
}

/** Render a declared `trajectory` view through the shared bounded structure stage. */
export function createTrajectoryViewRenderer(
  createViewer: MolecularViewerFactory,
  getTheme: () => 'light' | 'dark',
): ViewRenderer {
  return {
    id: 'trajectory',
    async render(view: ResultView, sources: ResolvedViewSources, host: HTMLElement, context) {
      const mapping = (view.mapping || {}) as TrajectoryMapping;
      const topologies: ResultFile[] = sources.topology ? [...sources.topology] : [];
      const coordinateArtifacts = sources.coordinates ? [...sources.coordinates] : [];
      const first = topologies[0];
      if (!first) throw new Error(t('results.trajectory.topologyMissing'));
      // A view that publishes one topology keeps failing the mount when its frames
      // are absent; several topologies stay mounted so the reader can pick another
      // design and read that design's own status.
      if (topologies.length === 1 && !associatedCoordinates(first, coordinateArtifacts, mapping.association)) {
        throw new Error(t('results.trajectory.coordinatesMissing'));
      }
      const format = String(mapping.coordinate_format || '').toLowerCase();
      if (!format) throw new Error(t('results.trajectory.formatMissing'));

      const controller = new StructureController(createViewer, { controlsCollapsed: true });
      const stage = element('section', 'structure-viewport trajectory-viewport');
      const viewerHost = element('div', 'structure-host');
      viewerHost.setAttribute('role', 'region');
      viewerHost.setAttribute('aria-label', t('results.trajectory.viewerLabel', { title: view.title }));
      const toolbar = element('div', 'structure-toolbar trajectory-toolbar');
      const shelf = element('div', 'structure-tool-secondary');
      const status = element('p', 'result-note trajectory-status');
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
      // The frame axis is the mapping's own vocabulary. A declared unit the view
      // does not recognize (``diffusion step``) is shown verbatim: it names what
      // one frame is, and nothing here converts it to physical time.
      const sample = mapping.frame_unit === 'sample';
      const declared = typeof mapping.frame_unit === 'string' ? mapping.frame_unit.trim() : '';
      // The unit is the Runner's declared vocabulary, emitted verbatim; only the
      // `sample` case has frontend-owned wording, because it also carries the
      // "not physical time" caution the API's own sample order needs.
      const unit = sample ? t('results.trajectory.sampleIndex') : declared || t('results.trajectory.frame');
      const previous = navigationButton('previous', t(sample ? 'results.trajectory.previous' : 'results.trajectory.previousFrame'));
      const next = navigationButton('next', t(sample ? 'results.trajectory.next' : 'results.trajectory.nextFrame'));
      const scrubber = element('input', 'trajectory-scrubber') as HTMLInputElement;
      scrubber.type = 'range';
      scrubber.min = '1';
      scrubber.step = '1';
      scrubber.disabled = true;
      scrubber.setAttribute('aria-label', unit);
      const label = element('span', 'trajectory-position');
      label.textContent = t('results.trajectory.position', { unit, frame: '—', total: '—' });
      shelf.append(label);
      // A view that publishes several topologies (one per design) must let the
      // reader choose which design's frames are on screen; showing the first
      // design's diffusion trajectory under another design's name is a
      // scientific mis-association.
      let selector: HTMLSelectElement | null = null;
      if (topologies.length > 1) {
        const field = element('label', 'structure-tool-field', t('results.trajectory.topology'));
        selector = element('select', 'trajectory-topology');
        topologies.forEach((topology, index) => {
          const option = element('option', undefined, resultFileName(topology));
          option.value = String(index);
          selector!.append(option);
        });
        field.append(selector);
        shelf.append(field);
      }
      toolbar.append(shelf);
      stage.append(toolbar, viewerHost, status);
      host.replaceChildren(stage);

      let destroyed = false;
      let loaded: TrajectoryInfo | null = null;
      context.signal.addEventListener('abort', () => { destroyed = true; stop(); controller.dispose(); }, { once: true });

      const show = (value: TrajectoryInfo): void => {
        loaded = value;
        scrubber.max = String(value.frameCount);
        scrubber.value = String(value.frame + 1);
        scrubber.disabled = value.frameCount < 2;
        previous.disabled = value.frameCount < 2;
        next.disabled = value.frameCount < 2;
        play.disabled = value.frameCount < 2;
        label.textContent = t('results.trajectory.position', {
          unit, frame: String(value.frame + 1), total: String(value.frameCount),
        });
        status.textContent = sample
          ? t('results.trajectory.frames', { count: value.frameCount })
          : t('results.trajectory.framesDeclared', { count: value.frameCount, unit: declared || unit.toLowerCase() });
      };
      const step = async (action: 'set' | 'advance', value: number): Promise<void> => {
        try {
          const updated = await controller.setTrajectoryFrame(action, value);
          if (!destroyed) show(updated);
        } catch (error) {
          if (!destroyed) status.textContent = (error as Error).message || t('results.trajectory.failed');
        }
      };
      previous.addEventListener('click', () => void step('advance', -1));
      next.addEventListener('click', () => void step('advance', 1));
      scrubber.addEventListener('input', () => void step('set', Number(scrubber.value) - 1));
      // Playback walks the declared frames at a fixed reading pace, labelled with
      // the mapping's own unit; it does not turn the axis into physical time.
      const play = navigationButton('play', t('results.trajectory.play'));
      play.setAttribute('aria-pressed', 'false');
      let timer: ReturnType<typeof setInterval> | null = null;
      const stop = (): void => {
        if (timer !== null) { clearInterval(timer); timer = null; }
        play.textContent = t('results.trajectory.play');
        play.setAttribute('aria-pressed', 'false');
      };
      play.addEventListener('click', () => {
        if (timer !== null || !loaded) { stop(); return; }
        if (loaded.frame + 1 >= loaded.frameCount) void step('set', 0);
        play.textContent = t('results.trajectory.pause');
        play.setAttribute('aria-pressed', 'true');
        timer = setInterval(() => {
          if (destroyed || !loaded || loaded.frame + 1 >= loaded.frameCount) { stop(); return; }
          void step('advance', 1);
        }, PLAYBACK_INTERVAL_MS);
      });
      const controls = element('div', 'structure-toolbar-actions');
      controls.append(previous, play, scrubber, next);
      toolbar.append(controls);

      // Each selection mounts that design's topology and its own frames; the
      // controller supersedes the previous load, so the same stage is reused.
      let request = 0;
      const load = async (topology: ResultFile): Promise<void> => {
        const current = ++request;
        stop();
        loaded = null;
        scrubber.disabled = true;
        scrubber.value = '1';
        previous.disabled = true;
        next.disabled = true;
        play.disabled = true;
        label.textContent = t('results.trajectory.position', { unit, frame: '—', total: '—' });
        const coordinates = associatedCoordinates(topology, coordinateArtifacts, mapping.association);
        if (!coordinates) {
          // The stage is emptied so the previous design's frames cannot be
          // mistaken for this design's.
          await controller.clear();
          if (!destroyed && current === request) status.textContent = t('results.trajectory.coordinatesMissing');
          return;
        }
        status.textContent = '';
        try {
          const info = await controller.mountTrajectory(viewerHost, topology, coordinates, format, getTheme());
          if (!destroyed && current === request) show(info);
        } catch (error) {
          // A superseded mount aborts; its failure belongs to the old selection.
          if (current !== request) return;
          // The frames of the design that was on screen are not this design's, so a
          // failed mount empties the stage the same way an absent coordinate does.
          await controller.clear();
          if (!destroyed && current === request) throw error;
          return;
        }
      };
      const failed = (error: Error): void => {
        if (!destroyed) status.textContent = error.message || t('results.trajectory.failed');
      };
      selector?.addEventListener('change', () => {
        const topology = topologies[Number(selector!.value)];
        if (topology) void load(topology).catch(failed);
      });

      try {
        await load(first);
      } catch (error) {
        // A single design keeps its existing failure contract; with several, one
        // design's unreadable frames must not take the selector down with it.
        if (topologies.length === 1) {
          controller.dispose();
          throw error;
        }
        failed(error as Error);
      }
      return {
        get frameCount(): number { return loaded?.frameCount || 0; },
        destroy: () => { destroyed = true; stop(); controller.dispose(); },
      };
    },
  };
}

function navigationButton(direction: 'previous' | 'next' | 'play', label: string): HTMLButtonElement {
  const button = element('button', 'result-button result-button-small') as HTMLButtonElement;
  button.type = 'button';
  button.dataset.trajectory = direction;
  button.textContent = label;
  button.disabled = true;
  return button;
}
