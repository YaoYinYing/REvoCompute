/*
 * Server-declared `trajectory` ResultView rendering: one Mol* stage fed by every
 * declared source (a topology plus binary coordinate frames), with frame count
 * and previous/next/scrub controls. The frame axis is labelled with the mapping's
 * own `frame_unit`; it never invents physical time.
 */
import type { ResultFile, ResultView } from '../../api/result-types';
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

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
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
      const topology: ResultFile | undefined = sources.topology?.[0];
      const coordinates: ResultFile | undefined = sources.coordinates?.[0];
      if (!topology) throw new Error(t('results.trajectory.topologyMissing'));
      if (!coordinates) throw new Error(t('results.trajectory.coordinatesMissing'));
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
      const previous = navigationButton('previous', t('results.trajectory.previous'));
      const next = navigationButton('next', t('results.trajectory.next'));
      const unit = mapping.frame_unit === 'sample' ? t('results.trajectory.sampleIndex') : t('results.trajectory.frame');
      const scrubber = element('input', 'trajectory-scrubber') as HTMLInputElement;
      scrubber.type = 'range';
      scrubber.min = '1';
      scrubber.step = '1';
      scrubber.disabled = true;
      scrubber.setAttribute('aria-label', unit);
      const label = element('span', 'trajectory-position');
      label.textContent = t('results.trajectory.position', { unit, frame: '—', total: '—' });
      shelf.append(label);
      toolbar.append(shelf);
      stage.append(toolbar, viewerHost, status);
      host.replaceChildren(stage);

      let destroyed = false;
      let loaded: TrajectoryInfo | null = null;
      context.signal.addEventListener('abort', () => { destroyed = true; controller.dispose(); }, { once: true });

      const show = (value: TrajectoryInfo): void => {
        loaded = value;
        scrubber.max = String(value.frameCount);
        scrubber.value = String(value.frame + 1);
        scrubber.disabled = value.frameCount < 2;
        previous.disabled = value.frameCount < 2;
        next.disabled = value.frameCount < 2;
        label.textContent = t('results.trajectory.position', {
          unit, frame: String(value.frame + 1), total: String(value.frameCount),
        });
        status.textContent = t('results.trajectory.frames', { count: value.frameCount });
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
      const controls = element('div', 'structure-toolbar-actions');
      controls.append(previous, scrubber, next);
      toolbar.append(controls);

      try {
        show(await controller.mountTrajectory(viewerHost, topology, coordinates, format, getTheme()));
      } catch (error) {
        controller.dispose();
        throw error;
      }
      return {
        get frameCount(): number { return loaded?.frameCount || 0; },
        destroy: () => { destroyed = true; controller.dispose(); },
      };
    },
  };
}

function navigationButton(direction: 'previous' | 'next', label: string): HTMLButtonElement {
  const button = element('button', 'result-button result-button-small') as HTMLButtonElement;
  button.type = 'button';
  button.dataset.trajectory = direction;
  button.textContent = label;
  button.disabled = true;
  return button;
}
