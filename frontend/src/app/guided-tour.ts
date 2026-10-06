import { createIcons, X } from 'lucide';
import { t } from './i18n';

/*
 * Guided learning: a hands-on path through the REvoCompute conceptual model
 * (Runner → input → Task → execution → result → artifacts/provenance).
 *
 * It is not a consumer "welcome carousel". Each step anchors to a real element
 * and explains the concept that element represents; steps that cannot anchor on
 * the current route, role, or viewport are skipped rather than faked. A step
 * whose surface is one concrete object — the result workspace needs a real task
 * id — is skipped cleanly when no such object exists; the tour never invents an
 * identifier. Progress is stored locally, the tour is restartable, and it never
 * takes over the page.
 *
 * Step copy is frontend-owned and lives in the i18n catalogs, so a locale change
 * localizes the tour exactly as it localizes the surrounding chrome.
 */

const doneKey = 'revocompute-tour-done';
const stepKey = 'revocompute-tour-step';
const resultKey = 'revocompute-tour-result';

interface TourStep {
  /** Route prefix that identifies the step's surface. */
  route: string;
  /** A real element on that surface the callout anchors to. */
  anchor: string;
  titleKey: string;
  bodyKey: string;
  docHref?: string;
  /** The surface is one concrete object page (a result), not a list route. */
  needsResult?: boolean;
}

const steps: TourStep[] = [
  {
    route: '/compute/dashboard',
    anchor: '.dashboard-stats',
    titleKey: 'tour.step.dashboard.title',
    bodyKey: 'tour.step.dashboard.body',
  },
  {
    route: '/compute/dashboard',
    anchor: '.task-card, .task-list',
    titleKey: 'tour.step.lifecycle.title',
    bodyKey: 'tour.step.lifecycle.body',
  },
  {
    route: '/runners',
    anchor: '.runner-catalog',
    titleKey: 'tour.step.runners.title',
    bodyKey: 'tour.step.runners.body',
  },
  {
    route: '/compute/create_task',
    anchor: '.ct-workbench, .ct-chooser',
    titleKey: 'tour.step.create.title',
    bodyKey: 'tour.step.create.body',
  },
  {
    route: '/compute/results',
    anchor: '.result-preview, .result-app',
    titleKey: 'tour.step.result.title',
    bodyKey: 'tour.step.result.body',
    docHref: 'https://yaoyinying.github.io/REvoCompute/',
    needsResult: true,
  },
];

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
    if (step.needsResult) {
      // A result page addresses one concrete task. Use a real result URL when the
      // tour entry recorded one; otherwise there is no object to show, so the step
      // is skipped rather than navigating to an id-less, nonexistent route.
      const target = this.resultTarget();
      if (!target) return this.show(index + 1);
      if (location.pathname !== target) {
        localStorage.setItem(stepKey, String(index));
        location.assign(target);
        return;
      }
    } else if (!location.pathname.startsWith(step.route)) {
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

  /** The concrete result page recorded at tour entry, gated to a real task id. */
  private resultTarget(): string | null {
    const url = localStorage.getItem(resultKey);
    return url && /^\/compute\/results\/[a-f0-9]{32}$/i.test(url) ? url : null;
  }

  private render(anchor: HTMLElement, step: TourStep, index: number): void {
    const title = t(step.titleKey), body = t(step.bodyKey);
    anchor.classList.add('tour-anchor');
    const callout = document.createElement('section');
    callout.className = 'tour-callout'; callout.setAttribute('role', 'dialog'); callout.setAttribute('aria-modal', 'false');
    callout.setAttribute('aria-label', title);
    callout.setAttribute('tabindex', '-1');
    const count = document.createElement('p'); count.className = 'tour-step-count'; count.textContent = t('tour.stepOf', { current: index + 1, total: steps.length });
    const heading = document.createElement('h2'); heading.textContent = title;
    const copy = document.createElement('p'); copy.className = 'tour-copy'; copy.textContent = body;
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

  private dismiss(): void { localStorage.setItem(doneKey, 'true'); localStorage.removeItem(stepKey); localStorage.removeItem(resultKey); this.close(); }
  private finish(): void { localStorage.removeItem(stepKey); localStorage.removeItem(resultKey); if (this.index >= steps.length - 1) localStorage.setItem(doneKey, 'true'); this.close(); }
}

/** One tour per page: the Dashboard launches it, navigation resumes it. */
export const guidedTour = new GuidedTour();

/**
 * Remember a concrete result URL so the result step can visit a real task rather
 * than a dangling route. The Dashboard records the first available result it knows
 * about before launching the tour. When it has no available result, the value left
 * by an earlier tour, a deleted task, or a previous session is cleared, so the step
 * can never navigate to a stale target.
 */
export function recordTourResult(url: string | null | undefined): void {
  const match = url ? /^\/compute\/results\/[a-f0-9]{32}$/i.exec(url) : null;
  if (match) localStorage.setItem(resultKey, match[0]);
  else localStorage.removeItem(resultKey);
}
