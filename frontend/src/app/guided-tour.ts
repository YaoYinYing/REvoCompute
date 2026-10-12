import { createIcons, X } from 'lucide';
import { t } from './i18n';

/*
 * Guided learning: hands-on paths through the REvoCompute conceptual model
 * (Runner → input → Task → execution → result → artifacts/provenance).
 *
 * There are three job-oriented flows, not one generic welcome carousel, and each
 * owns its own progress state: finishing or dismissing the create-your-first-Task
 * tour never marks the result or the admin tour done. A flow is only ever offered
 * where its job is: the create tour from the Dashboard register, the result tour
 * from a result workspace that actually exists, the admin tour from the
 * administrator surfaces.
 *
 * It is not a consumer "welcome carousel". Each step anchors to a real element
 * and explains the concept that element represents; steps that cannot anchor on
 * the current route, role, or viewport are skipped rather than faked. A step
 * whose surface is one concrete object — the result workspace needs a real task
 * id — is skipped cleanly when no such object exists; the tour never invents an
 * identifier, and no step ever submits, cancels, or mutates anything.
 *
 * Step copy is frontend-owned and lives in the i18n catalogs, so a locale change
 * localizes the tour exactly as it localizes the surrounding chrome.
 */

const DOCS_HREF = 'https://yaoyinying.github.io/REvoCompute/';

/** Which flow is in progress. Written when a flow starts, cleared when it ends. */
const activeKey = 'revocompute-tour-flow';

export type TourFlowId = 'create' | 'results' | 'admin';

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

interface TourFlow {
  id: TourFlowId;
  /**
   * Separate progress state per flow. The three flows never share a key, so a
   * completion in one is not a completion in another.
   */
  doneKey: string;
  stepKey: string;
  /** The create flow's recorded result target; only that flow stores one. */
  targetKey?: string;
  /** Launcher label for a flow that has never run. */
  entryKey: string;
  /** Routes on which this flow's entry is offered. */
  entryRoutes: string[];
  /**
   * The identity this flow's completion is bound to. A flow bound to an object
   * (a result) is offered again for a different object, so a completed tour
   * cannot be stale evidence about a result the reader has never seen.
   */
  scope: () => string;
  steps: TourStep[];
}

const createFlow: TourFlow = {
  id: 'create',
  doneKey: 'revocompute-tour-done',
  stepKey: 'revocompute-tour-step',
  targetKey: 'revocompute-tour-result',
  entryKey: 'tour.entry',
  // The create tour is a path through the register, so its entry lives on the
  // register. The Dashboard mounts it explicitly; `offer` is a no-op there.
  entryRoutes: ['/compute/dashboard'],
  scope: () => 'true',
  steps: [
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
      docHref: DOCS_HREF,
      needsResult: true,
    },
  ],
};

/**
 * The concrete result page this session is looking at, read from the route the
 * reader actually opened. Empty when the address is not a task result, which is
 * also what makes a stored completion for a *different* result inapplicable.
 */
function resultScope(): string {
  const match = /^\/compute\/results\/([0-9a-f]{32})$/i.exec(location.pathname);
  return match ? match[1]!.toLowerCase() : '';
}

const resultsFlow: TourFlow = {
  id: 'results',
  doneKey: 'revocompute-tour-results-done',
  stepKey: 'revocompute-tour-results-step',
  entryKey: 'tour.entry.results',
  // The result flow is offered on a concrete result page, and only when the
  // reader can actually be on one — the entry never appears as a default path
  // for a first-time user who has no finished result to read.
  entryRoutes: ['/compute/results/'],
  scope: resultScope,
  steps: [
    {
      route: '/compute/results/',
      anchor: '.result-header',
      titleKey: 'tour.step.resultHeader.title',
      bodyKey: 'tour.step.resultHeader.body',
      docHref: DOCS_HREF,
    },
    {
      route: '/compute/results/',
      anchor: '.result-preview',
      titleKey: 'tour.step.resultPreview.title',
      bodyKey: 'tour.step.resultPreview.body',
      docHref: DOCS_HREF,
    },
    {
      route: '/compute/results/',
      anchor: '.result-record',
      titleKey: 'tour.step.resultRecord.title',
      bodyKey: 'tour.step.resultRecord.body',
      docHref: DOCS_HREF,
    },
  ],
};

const adminFlow: TourFlow = {
  id: 'admin',
  doneKey: 'revocompute-tour-admin-done',
  stepKey: 'revocompute-tour-admin-step',
  entryKey: 'tour.entry.admin',
  // Offered on every Administration destination, and never anywhere else.
  entryRoutes: ['/compute/runner_fleet', '/compute/user_control', '/compute/configuration', '/compute/logs'],
  scope: () => 'true',
  // Administration is read-only here: every step names what a status, a capacity
  // figure, or a log line means and how to read it. No step activates, promotes,
  // repairs, resets a credit, or opens a privileged mutation.
  steps: [
    {
      route: '/compute/runner_fleet',
      anchor: '.admin-table-scroll',
      titleKey: 'tour.step.fleet.title',
      bodyKey: 'tour.step.fleet.body',
      docHref: DOCS_HREF,
    },
    {
      route: '/compute/user_control',
      anchor: '.user-admin-table',
      titleKey: 'tour.step.users.title',
      bodyKey: 'tour.step.users.body',
      docHref: DOCS_HREF,
    },
    {
      route: '/compute/configuration',
      anchor: '.config-type-list',
      titleKey: 'tour.step.configuration.title',
      bodyKey: 'tour.step.configuration.body',
      docHref: DOCS_HREF,
    },
    {
      route: '/compute/logs',
      anchor: '.admin-log-output',
      titleKey: 'tour.step.logs.title',
      bodyKey: 'tour.step.logs.body',
      docHref: DOCS_HREF,
    },
  ],
};

const flows: TourFlow[] = [createFlow, resultsFlow, adminFlow];

function flowFor(id: string | null): TourFlow | null {
  return flows.find(flow => flow.id === id) ?? null;
}

/** Whether a route belongs to the flow's own surfaces. */
function ownsRoute(flow: TourFlow, pathname: string): boolean {
  return flow.steps.some(step => pathname.startsWith(step.route));
}

/** Whether this route is a legitimate place to offer the flow's entry. */
function offersEntry(flow: TourFlow, pathname: string): boolean {
  return flow.entryRoutes.some(route => pathname.startsWith(route));
}

export class GuidedTour {
  private callout: HTMLElement | null = null;
  private cleanup: (() => void) | null = null;
  private flow: TourFlow | null = null;
  private index = 0;
  private disposal: ((event: Event) => void) | null = null;

  // The callout is appended under body, where a route render cannot reach it: it
  // lives outside the outlet the next route replaces, so a route change would
  // otherwise leave a stale overlay and its listeners attached to the new page.
  // One pagehide listener, installed once for the tour's lifetime, disposes the
  // overlay as this document is navigated away from. A bfcache restore keeps the
  // document, so it is left alone.
  constructor() {
    if (typeof document === 'undefined' || !document.addEventListener) return;
    this.disposal = event => { if (!(event as PageTransitionEvent).persisted) this.close(); };
    document.addEventListener('pagehide', this.disposal);
  }

  /** A flow is done when its completion matches the object it is bound to. */
  private isDone(flow: TourFlow): boolean {
    const scope = flow.scope();
    return scope !== '' && localStorage.getItem(flow.doneKey) === scope;
  }

  private inProgress(flow: TourFlow): boolean {
    return localStorage.getItem(flow.stepKey) !== null;
  }

  private storedStep(flow: TourFlow): number {
    const value = Number(localStorage.getItem(flow.stepKey));
    return Number.isInteger(value) && value >= 0 && value < flow.steps.length ? value : 0;
  }

  /** The entry for one flow: visible but not dominant, and restartable later. */
  launcher(flowId: TourFlowId = 'create'): HTMLButtonElement {
    const flow = flowFor(flowId)!;
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'ghost-button tour-launcher';
    button.dataset.tourStart = flow.id;
    button.textContent = this.isDone(flow) || this.inProgress(flow) ? t('tour.restart') : t(flow.entryKey);
    button.addEventListener('click', () => this.start(flow.id, 0));
    return button;
  }

  /**
   * Offer the flow that belongs on this route, without taking the page over.
   *
   * The register mounts its own entry explicitly; this is the automatic half for
   * the flows whose surface is a page the reader lands on rather than a register
   * they act from: a result workspace offers its tour, and every Administration
   * destination offers the admin tour. A flow already in progress resumes through
   * :meth:`resumeIfActive` and is never offered a second entry, and the entry is
   * only *added* — the page keeps every control it already had.
   */
  offer(): void {
    // The create flow's register mounts its own entry explicitly, so only the
    // flows whose surface is a page the reader lands on are offered here.
    const flow = flows.find(candidate => candidate.id !== 'create' && offersEntry(candidate, location.pathname));
    if (!flow || this.inProgress(flow) || this.isDone(flow)) return;
    const host = document.querySelector<HTMLElement>('main.result-app, main.admin-page .page-heading');
    if (!host || host.querySelector('.tour-launcher')) return;
    const actions = host.querySelector<HTMLElement>('.result-header-actions, .page-actions');
    (actions ?? host).append(this.launcher(flow.id));
  }

  /**
   * Resume the flow this route belongs to after a route change.
   *
   * Only the flow that is in progress *and* whose current step lives on this
   * route resumes: an unfinished tour must never pull a reader off an unrelated
   * page, and a completed one stays completed.
   */
  resumeIfActive(): void {
    const flow = flowFor(localStorage.getItem(activeKey));
    if (!flow || this.isDone(flow) || !this.inProgress(flow)) return;
    const index = this.storedStep(flow);
    const step = flow.steps[index];
    if (!step || !location.pathname.startsWith(step.route)) return;
    this.show(flow, index);
  }

  /**
   * Start a flow from its first step. A flow only starts on a surface it owns,
   * so a stray call cannot walk an administrator into the reader's tour or the
   * reverse.
   */
  start(flowId: TourFlowId, index: number): void {
    const flow = flowFor(flowId);
    if (!flow || !ownsRoute(flow, location.pathname)) return;
    localStorage.setItem(activeKey, flow.id);
    localStorage.removeItem(flow.doneKey);
    this.show(flow, index);
  }

  private show(flow: TourFlow, index: number): void {
    this.close();
    const step = flow.steps[index];
    if (!step) return this.finish(flow, index);
    if (step.needsResult) {
      // A result page addresses one concrete task. Use a real result URL when the
      // tour entry recorded one; otherwise there is no object to show, so the step
      // is skipped rather than navigating to an id-less, nonexistent route.
      const target = this.target(flow);
      if (!target) return this.show(flow, index + 1);
      if (location.pathname !== target) {
        localStorage.setItem(flow.stepKey, String(index));
        location.assign(target);
        return;
      }
    } else if (!location.pathname.startsWith(step.route)) {
      // The step belongs to another surface: remember where we are and go there.
      // Re-assigning the current address would reload the page without advancing
      // the tour, so a step that already matches its own route never navigates.
      localStorage.setItem(flow.stepKey, String(index));
      if (location.pathname !== step.route) location.assign(step.route);
      return;
    }
    const anchor = document.querySelector<HTMLElement>(step.anchor);
    if (!anchor) {
      // Skip a step whose element is absent because of role, viewport, or state.
      return this.show(flow, index + 1);
    }
    localStorage.setItem(flow.stepKey, String(index));
    this.flow = flow;
    this.index = index;
    this.render(flow, anchor, step, index);
  }

  /** The concrete result page recorded at create-tour entry, gated to a real id. */
  private target(flow: TourFlow): string | null {
    if (!flow.targetKey) return null;
    const url = localStorage.getItem(flow.targetKey);
    return url && /^\/compute\/results\/[a-f0-9]{32}$/i.test(url) ? url : null;
  }

  private render(flow: TourFlow, anchor: HTMLElement, step: TourStep, index: number): void {
    const title = t(step.titleKey), body = t(step.bodyKey);
    anchor.classList.add('tour-anchor');
    const callout = document.createElement('section');
    callout.className = 'tour-callout'; callout.setAttribute('role', 'dialog'); callout.setAttribute('aria-modal', 'false');
    callout.setAttribute('aria-label', title);
    callout.setAttribute('tabindex', '-1');
    const count = document.createElement('p'); count.className = 'tour-step-count'; count.textContent = t('tour.stepOf', { current: index + 1, total: flow.steps.length });
    const heading = document.createElement('h2'); heading.textContent = title;
    const copy = document.createElement('p'); copy.className = 'tour-copy'; copy.textContent = body;
    const close = document.createElement('button'); close.type = 'button'; close.className = 'icon-button tour-close'; close.title = t('tour.close'); close.setAttribute('aria-label', t('tour.close')); close.innerHTML = '<i data-lucide="x" aria-hidden="true"></i>';
    close.addEventListener('click', () => this.finish(flow, index));
    const footer = document.createElement('footer');
    const dismiss = document.createElement('button'); dismiss.type = 'button'; dismiss.className = 'ghost-button'; dismiss.textContent = t('tour.dismiss'); dismiss.addEventListener('click', () => this.dismiss(flow));
    const skip = document.createElement('button'); skip.type = 'button'; skip.className = 'ghost-button'; skip.textContent = t('tour.skip'); skip.addEventListener('click', () => this.finish(flow, index));
    const back = document.createElement('button'); back.type = 'button'; back.className = 'secondary-button'; back.textContent = t('tour.back'); back.disabled = index === 0; back.addEventListener('click', () => this.show(flow, index - 1));
    const next = document.createElement('button'); next.type = 'button'; next.className = 'primary-button'; next.textContent = index === flow.steps.length - 1 ? t('tour.finish') : t('tour.next'); next.addEventListener('click', () => this.show(flow, index + 1));
    footer.append(dismiss, back, skip, next);
    callout.append(count, close, heading, copy);
    if (step.docHref) { const link = document.createElement('a'); link.href = step.docHref; link.textContent = t('public.nav.documentation'); callout.append(link); }
    callout.append(footer);

    callout.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); this.finish(flow, index); }
      else if (event.key === 'ArrowRight') { event.preventDefault(); this.show(flow, index + 1); }
      else if (event.key === 'ArrowLeft') { event.preventDefault(); this.show(flow, index - 1); }
    });

    const position = (): void => {
      const rect = anchor.getBoundingClientRect();
      const width = Math.min(384, window.innerWidth - 32);
      const left = Math.min(Math.max(16, rect.left), window.innerWidth - width - 16);
      const below = rect.bottom + 12;
      const top = below + 240 < window.innerHeight ? below : Math.max(16, rect.top - 260);
      callout.style.left = `${left}px`; callout.style.top = `${top}px`;
      // The shell owns the viewport's lower corner with its fixed feedback column
      // (notices and toasts). A callout that would land on that column keeps its
      // bottom edge above the column's measured top, so neither layer loses a
      // control to the other.
      const occupied = document.querySelector<HTMLElement>('.app-feedback')?.getBoundingClientRect();
      if (!occupied?.height) return;
      const placed = callout.getBoundingClientRect();
      if (placed.right <= occupied.left || placed.left >= occupied.right || placed.bottom <= occupied.top) return;
      callout.style.top = `${Math.max(16, occupied.top - placed.height - 8)}px`;
    };
    document.body.append(callout);
    position();
    window.addEventListener('resize', position);
    // The column's content arrives asynchronously (a notice, a toast appended or
    // expired, a notice opened), so placement follows the column the shell actually
    // renders rather than the single reading taken when the tour opened.
    const column = document.querySelector<HTMLElement>('.app-feedback');
    const clearance = column ? new MutationObserver(() => position()) : null;
    clearance?.observe(column!, { childList: true, subtree: true, attributes: true });
    this.callout = callout;
    createIcons({ icons: { X }, root: callout });
    callout.focus();
    anchor.scrollIntoView({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    this.cleanup = () => { window.removeEventListener('resize', position); clearance?.disconnect(); };
  }

  /** Remove every overlay and listener this tour created. Safe to call twice. */
  private close(): void {
    this.cleanup?.(); this.cleanup = null;
    document.querySelectorAll('.tour-anchor').forEach(node => node.classList.remove('tour-anchor'));
    this.callout?.remove(); this.callout = null;
  }

  private endFlow(flow: TourFlow): void {
    localStorage.removeItem(flow.stepKey);
    if (flow.targetKey) localStorage.removeItem(flow.targetKey);
    if (localStorage.getItem(activeKey) === flow.id) localStorage.removeItem(activeKey);
    this.close();
  }

  private dismiss(flow: TourFlow): void { localStorage.setItem(flow.doneKey, flow.scope()); this.endFlow(flow); }
  private finish(flow: TourFlow, index: number): void {
    // Reaching the end of the flow is a completion; leaving early (skip, close,
    // Escape) is not, so the entry stays for a reader who wants to come back.
    if (index >= flow.steps.length - 1) localStorage.setItem(flow.doneKey, flow.scope());
    this.endFlow(flow);
  }
}

/** One tour per page: the surfaces launch a flow, navigation resumes it. */
export const guidedTour = new GuidedTour();

/**
 * Remember a concrete result URL so the create flow's result step can visit a real
 * task rather than a dangling route. The Dashboard records the first available
 * result it knows about before launching the tour. When it has no available
 * result, the value left by an earlier tour, a deleted task, or a previous session
 * is cleared, so the step can never navigate to a stale target.
 */
export function recordTourResult(url: string | null | undefined): void {
  const match = url ? /^\/compute\/results\/[a-f0-9]{32}$/i.exec(url) : null;
  if (match) localStorage.setItem('revocompute-tour-result', match[0]);
  else localStorage.removeItem('revocompute-tour-result');
}
