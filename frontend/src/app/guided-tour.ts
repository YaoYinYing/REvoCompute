import { createIcons, X } from 'lucide';
import { t } from './i18n';

/*
 * Guided learning: a hands-on path through the REvoCompute conceptual model
 * (Runner → input → Task → execution → result → artifacts/provenance).
 *
 * It is not a consumer "welcome carousel". Each step anchors to a real element
 * and explains the concept that element represents; steps that cannot anchor on
 * the current route, role, or viewport are skipped rather than faked. Progress
 * is stored locally, the tour is restartable, and it never takes over the page.
 */

const doneKey = 'revocompute-tour-done';
const stepKey = 'revocompute-tour-step';

interface TourStep {
  route: string;
  anchor: string;
  title: string;
  body: string;
  docHref?: string;
}

const steps: TourStep[] = [
  {
    route: '/compute/dashboard',
    anchor: '.dashboard-stats',
    title: 'A task is a computational object',
    body: 'Every submission becomes one Task with its own identity, lifecycle, metadata, and result. These totals are that collection at a glance — not five separate dashboards.',
  },
  {
    route: '/compute/dashboard',
    anchor: '.task-card, .task-list',
    title: 'Watch the lifecycle here',
    body: 'A Task moves from pending to running to finished. The card is where you inspect its machine facts — type, ID, timestamps, wall time — and open its result once it exists.',
  },
  {
    route: '/runners',
    anchor: '.runner-catalog',
    title: 'A Runner is a scientific method',
    body: 'The catalog is a registry of methods and their runtime contracts: what each one does, which input roles it accepts, what it produces, and how it is accessed.',
  },
  {
    route: '/compute/create_task',
    anchor: '.ct-workbench, .ct-chooser',
    title: 'Prepare, then submit once',
    body: 'Create Task is where you supply inputs and parameters. The owning task.yaml defines their meaning, so the form always reflects the server contract. Submitting snapshots exactly what will run.',
  },
  {
    route: '/compute/results',
    anchor: '.result-preview, .result-app',
    title: 'The result is the loudest thing',
    body: 'The result workspace shows the scientific artifact first, with its files, integrity, and provenance alongside. You can always trace what produced it and download the exact artifacts.',
    docHref: 'https://yaoyinying.github.io/REvoCompute/',
  },
];

function attribute(selector: string, name: string): string {
  const first = selector.split(',')[0]!.trim();
  return `data-tour-${name}="${first}"`;
}

export class GuidedTour {
  private callout: HTMLElement | null = null;
  private index = 0;

  private get done(): boolean { return localStorage.getItem(doneKey) === 'true'; }

  private storedStep(): number {
    const value = Number(localStorage.getItem(stepKey));
    return Number.isInteger(value) && value >= 0 && value < steps.length ? value : 0;
  }

  /** The Dashboard entry: visible but not dominant, and restartable later. */
  launcher(): HTMLButtonElement {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'ghost-button tour-launcher'; button.dataset.tourStart = '';
    button.textContent = this.done || localStorage.getItem(stepKey) !== null ? t('tour.restart') : t('tour.entry');
    button.addEventListener('click', () => this.start(0));
    return button;
  }

  /** Resume an in-progress tour after a route change; do nothing once finished. */
  resumeIfActive(): void {
    const step = localStorage.getItem(stepKey);
    if (step === null || this.done) return;
    this.show(this.storedStep());
  }

  start(index: number): void {
    localStorage.removeItem(doneKey);
    this.show(index);
  }

  private show(index: number): void {
    this.close();
    const step = steps[index];
    if (!step) return this.finish();
    if (!location.pathname.startsWith(step.route)) {
      // The step belongs to another surface: remember where we are and go there.
      localStorage.setItem(stepKey, String(index));
      location.assign(step.route);
      return;
    }
    const anchor = document.querySelector<HTMLElement>(step.anchor);
    if (!anchor) {
      // Skip a step whose element is absent because of role, viewport, or state.
      return this.show(index + 1);
    }
    localStorage.setItem(stepKey, String(index));
    this.index = index;
    this.render(anchor, step, index);
  }

  private render(anchor: HTMLElement, step: TourStep, index: number): void {
    anchor.classList.add('tour-anchor');
    const callout = document.createElement('section');
    callout.className = 'tour-callout'; callout.setAttribute('role', 'dialog'); callout.setAttribute('aria-modal', 'false');
    callout.setAttribute('aria-label', step.title);
    callout.setAttribute('tabindex', '-1');
    const count = document.createElement('p'); count.className = 'tour-step-count'; count.textContent = t('tour.stepOf', { current: index + 1, total: steps.length });
    const heading = document.createElement('h2'); heading.textContent = step.title;
    const copy = document.createElement('p'); copy.className = 'tour-copy'; copy.textContent = step.body;
    const close = document.createElement('button'); close.type = 'button'; close.className = 'icon-button tour-close'; close.title = t('tour.close'); close.setAttribute('aria-label', t('tour.close')); close.innerHTML = '<i data-lucide="x" aria-hidden="true"></i>';
    close.addEventListener('click', () => this.finish());
    const footer = document.createElement('footer');
    const dismiss = document.createElement('button'); dismiss.type = 'button'; dismiss.className = 'ghost-button'; dismiss.textContent = t('tour.dismiss'); dismiss.addEventListener('click', () => this.dismiss());
    const skip = document.createElement('button'); skip.type = 'button'; skip.className = 'ghost-button'; skip.textContent = t('tour.skip'); skip.addEventListener('click', () => this.finish());
    const back = document.createElement('button'); back.type = 'button'; back.className = 'secondary-button'; back.textContent = t('tour.back'); back.disabled = index === 0; back.addEventListener('click', () => this.show(index - 1));
    const next = document.createElement('button'); next.type = 'button'; next.className = 'primary-button'; next.textContent = index === steps.length - 1 ? t('tour.finish') : t('tour.next'); next.addEventListener('click', () => this.show(index + 1));
    footer.append(dismiss, back, skip, next);
    callout.append(count, close, heading, copy);
    if (step.docHref) { const link = document.createElement('a'); link.href = step.docHref; link.textContent = t('public.nav.documentation'); callout.append(link); }
    callout.append(footer);

    callout.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); this.finish(); }
      else if (event.key === 'ArrowRight') { event.preventDefault(); this.show(this.index + 1); }
      else if (event.key === 'ArrowLeft') { event.preventDefault(); this.show(this.index - 1); }
    });

    const position = (): void => {
      const rect = anchor.getBoundingClientRect();
      const width = Math.min(384, window.innerWidth - 32);
      const left = Math.min(Math.max(16, rect.left), window.innerWidth - width - 16);
      const below = rect.bottom + 12;
      const top = below + 240 < window.innerHeight ? below : Math.max(16, rect.top - 260);
      callout.style.left = `${left}px`; callout.style.top = `${top}px`;
    };
    document.body.append(callout);
    position();
    window.addEventListener('resize', position);
    this.callout = callout;
    createIcons({ icons: { X }, root: callout });
    callout.focus();
    anchor.scrollIntoView({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    this.cleanup = () => window.removeEventListener('resize', position);
  }

  private cleanup: (() => void) | null = null;

  private close(): void {
    this.cleanup?.(); this.cleanup = null;
    document.querySelectorAll('.tour-anchor').forEach(node => node.classList.remove('tour-anchor'));
    this.callout?.remove(); this.callout = null;
  }

  private dismiss(): void { localStorage.setItem(doneKey, 'true'); localStorage.removeItem(stepKey); this.close(); }
  private finish(): void { localStorage.removeItem(stepKey); if (this.index >= steps.length - 1) localStorage.setItem(doneKey, 'true'); this.close(); }
}

/** One tour per page: the Dashboard launches it, navigation resumes it. */
export const guidedTour = new GuidedTour();
