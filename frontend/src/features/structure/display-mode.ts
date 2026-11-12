/*
 * One mounted molecular stage, three presentation modes.
 *
 * The viewer and its WebGL canvas stay mounted for the whole lifetime of the
 * stage. Switching mode only changes layout attributes, the browser fullscreen
 * element, and the focus trap; it never reloads the structure, resets the
 * camera, or discards the trajectory frame.
 */
export type StageDisplayMode = 'normal' | 'expand' | 'maximize';

export interface DisplayModeLabels {
  group: string;
  normal: string;
  expand: string;
  maximize: string;
  /** Announced (and visibly labelled) when native fullscreen is unavailable. */
  fullscreenFallback: string;
  expanded: string;
  maximized: string;
  collapsed: string;
}

export interface DisplayModeOptions {
  /** The one stage that contains the mounted viewer. */
  stage: HTMLElement;
  /** Called after a mode change and after fullscreen transitions. */
  resize: () => void;
  labels: DisplayModeLabels;
  document?: Document;
  requestFrame?: (callback: () => void) => number | ReturnType<typeof setTimeout>;
}

type FullscreenDocument = Pick<Document, 'fullscreenEnabled' | 'fullscreenElement' | 'exitFullscreen' | 'addEventListener' | 'removeEventListener'> & {
  fullscreenElement?: Element | null;
};

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** Extract a mode from an external value; anything else stays normal. */
export function normalizeDisplayMode(value: unknown): StageDisplayMode {
  return value === 'expand' || value === 'maximize' ? value : 'normal';
}

/** Native fullscreen is usable only when the document enables it. */
export function canUseFullscreen(document: FullscreenDocument | null | undefined): boolean {
  return Boolean(document && document.fullscreenEnabled === true);
}

/** Whether a requested maximize can use native fullscreen or must fall back. */
export function maximizeSupport(document: FullscreenDocument | null | undefined): { fallback: boolean } {
  return { fallback: !canUseFullscreen(document) };
}

function focusable(scope: ParentNode): HTMLElement[] {
  return Array.from(scope.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter(element => !element.hasAttribute('hidden') && element.getAttribute('aria-hidden') !== 'true');
}

export class DisplayModeController {
  private current: StageDisplayMode = 'normal';
  private disposed = false;
  private previousFocus: HTMLElement | null = null;
  private backdrop: HTMLElement | null = null;
  private status: HTMLElement | null = null;
  private overlayActive = false;
  private savedRole: string | null = null;
  private savedModal: string | null = null;
  private savedTabIndex: string | null = null;
  private frameRequest: number | ReturnType<typeof setTimeout> | null = null;
  private readonly listeners = new Set<(mode: StageDisplayMode) => void>();
  private readonly doc: Document;
  private readonly requestFrame: (callback: () => void) => number | ReturnType<typeof setTimeout>;
  private readonly keydown = (event: KeyboardEvent): void => this.trap(event);
  private readonly fullscreenChange = (): void => this.syncFullscreen();

  constructor(private readonly options: DisplayModeOptions) {
    this.doc = options.document ?? document;
    this.requestFrame = options.requestFrame ?? ((callback) => {
      if (typeof requestAnimationFrame === 'function') return requestAnimationFrame(callback);
      return setTimeout(callback, 0);
    });
    // Tests and constrained embeds may hand over a minimal document surface;
    // the controller degrades to layout-only mode rather than failing to mount.
    if (typeof this.doc.addEventListener === 'function') this.doc.addEventListener('fullscreenchange', this.fullscreenChange);
  }

  mode(): StageDisplayMode {
    return this.current;
  }

  onChange(listener: (mode: StageDisplayMode) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async setMode(mode: StageDisplayMode): Promise<void> {
    if (this.disposed) return;
    const next = normalizeDisplayMode(mode);
    if (next === this.current) return;
    const previous = this.current;
    const wasFallback = previous === 'maximize' && this.isFullscreenFallback();
    const wasOverlay = previous === 'expand' || wasFallback;
    this.current = next;
    if (previous === 'maximize' && !wasFallback) await this.leaveFullscreen();
    if (wasOverlay) this.teardownOverlay();
    if (next === 'normal') {
      this.clearModeAttributes();
      this.announce(this.options.labels.collapsed);
    } else if (next === 'expand') {
      this.enterOverlay('expand', false);
    } else if (maximizeSupport(this.doc as FullscreenDocument | null).fallback) {
      this.enterOverlay('maximize', true);
    } else {
      this.options.stage.dataset.displayMode = 'maximize';
      try {
        await this.requestFullscreen();
        this.announce(this.options.labels.maximized);
      } catch {
        this.enterOverlay('maximize', true);
      }
    }
    this.notify();
  }

  destroy(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (typeof this.doc.removeEventListener === 'function') this.doc.removeEventListener('fullscreenchange', this.fullscreenChange);
    this.clearModeAttributes();
    this.removeOverlay(true);
    if (this.frameRequest !== null) {
      if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(this.frameRequest as number);
      clearTimeout(this.frameRequest as ReturnType<typeof setTimeout>);
      this.frameRequest = null;
    }
    if (this.isFullscreenSurface(this.options.stage)) {
      try { void Promise.resolve(this.doc.exitFullscreen?.()).catch(() => undefined); } catch { /* Already leaving. */ }
    }
    this.listeners.clear();
  }

  private async requestFullscreen(): Promise<void> {
    const surface = this.options.stage;
    if (typeof surface.requestFullscreen !== 'function') throw new Error('Fullscreen is unavailable.');
    await surface.requestFullscreen();
  }

  private async leaveFullscreen(): Promise<void> {
    if (this.isFullscreenSurface(this.options.stage)) {
      try { await this.doc.exitFullscreen?.(); } catch { /* The element already left fullscreen. */ }
    }
  }

  private isFullscreenSurface(surface: Element): boolean {
    return this.doc.fullscreenElement === surface;
  }

  private isFullscreenFallback(): boolean {
    return this.options.stage.dataset.fullscreenFallback === 'true';
  }

  private syncFullscreen(): void {
    if (this.disposed || this.current !== 'maximize' || this.isFullscreenFallback()) return;
    if (!this.isFullscreenSurface(this.options.stage)) {
      this.current = 'normal';
      this.clearModeAttributes();
      this.notify();
    }
    this.resize();
  }

  private enterOverlay(mode: StageDisplayMode, fallback: boolean): void {
    if (this.overlayActive) this.removeOverlay(false);
    this.overlayActive = true;
    const stage = this.options.stage;
    this.savedRole = stage.getAttribute('role');
    this.savedModal = stage.getAttribute('aria-modal');
    this.savedTabIndex = stage.getAttribute('tabindex');
    this.previousFocus = (this.doc.activeElement as HTMLElement | null) ?? null;
    stage.dataset.displayMode = mode;
    if (fallback) stage.dataset.fullscreenFallback = 'true';
    else delete stage.dataset.fullscreenFallback;
    stage.setAttribute('role', 'dialog');
    stage.setAttribute('aria-modal', 'true');
    stage.setAttribute('aria-label', this.options.labels.group);

    const backdrop = this.doc.createElement('div');
    backdrop.className = 'structure-mode-backdrop';
    backdrop.addEventListener('pointerdown', () => { void this.setMode('normal'); });
    this.doc.body?.append?.(backdrop);
    this.backdrop = backdrop;

    const status = this.doc.createElement('p');
    status.className = 'structure-mode-status sr-only';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.textContent = fallback ? this.options.labels.fullscreenFallback : this.options.labels.expanded;
    stage.append(status);
    this.status = status;

    if (typeof this.doc.addEventListener === 'function') this.doc.addEventListener('keydown', this.keydown, true);
    stage.setAttribute('tabindex', '-1');
    const first = focusable(stage)[0] ?? stage;
    first.focus();
    this.resize();
  }

  private teardownOverlay(): void {
    this.removeOverlay(true);
  }

  private removeOverlay(restoreFocus: boolean): void {
    if (!this.overlayActive) return;
    this.overlayActive = false;
    if (typeof this.doc.removeEventListener === 'function') this.doc.removeEventListener('keydown', this.keydown, true);
    this.backdrop?.remove();
    this.backdrop = null;
    this.status?.remove();
    this.status = null;
    const stage = this.options.stage;
    if (this.savedRole === null) stage.removeAttribute('role');
    else stage.setAttribute('role', this.savedRole);
    if (this.savedModal === null) stage.removeAttribute('aria-modal');
    else stage.setAttribute('aria-modal', this.savedModal);
    if (this.savedTabIndex === null) stage.removeAttribute('tabindex');
    else stage.setAttribute('tabindex', this.savedTabIndex);
    this.savedRole = null;
    this.savedModal = null;
    this.savedTabIndex = null;
    delete stage.dataset.displayMode;
    delete stage.dataset.fullscreenFallback;
    const previous = this.previousFocus;
    this.previousFocus = null;
    if (restoreFocus) previous?.focus();
  }

  private clearModeAttributes(): void {
    delete this.options.stage.dataset.displayMode;
    delete this.options.stage.dataset.fullscreenFallback;
  }

  private trap(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      void this.setMode('normal');
      return;
    }
    if (event.key !== 'Tab') return;
    const stage = this.options.stage;
    const items = focusable(stage);
    if (!items.length) { event.preventDefault(); stage.focus(); return; }
    const first = items[0]!;
    const last = items[items.length - 1]!;
    const active = this.doc.activeElement;
    if (typeof stage.contains === 'function' && active && !stage.contains(active)) {
      event.preventDefault();
      first.focus();
      return;
    }
    if (event.shiftKey) {
      if (active === first || active === stage) { event.preventDefault(); last.focus(); }
    } else if (active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  private announce(message: string): void {
    if (this.status) this.status.textContent = message;
  }

  private notify(): void {
    this.listeners.forEach(listener => listener(this.current));
  }

  private resize(): void {
    if (this.frameRequest !== null) {
      if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(this.frameRequest as number);
      clearTimeout(this.frameRequest as ReturnType<typeof setTimeout>);
    }
    this.frameRequest = this.requestFrame(() => {
      this.frameRequest = null;
      this.options.resize();
    });
  }
}

export interface DisplayModeControlOptions extends DisplayModeOptions {
  /** Where the three mode buttons are appended. */
  container: HTMLElement;
}

export interface DisplayModeControls {
  element: HTMLElement;
  controller: DisplayModeController;
  destroy(): void;
}

/**
 * Three accessible mode buttons bound to one controller. Standard buttons are
 * keyboard reachable; Escape is handled by the controller while an overlay is
 * open, and native fullscreen keeps the browser's own escape behavior.
 */
export function createDisplayModeControls(options: DisplayModeControlOptions): DisplayModeControls {
  const documentRef = options.document ?? document;
  const controller = new DisplayModeController(options);
  const group = documentRef.createElement('div');
  group.className = 'structure-display-modes';
  group.setAttribute('role', 'group');
  group.setAttribute('aria-label', options.labels.group);
  const buttons = new Map<StageDisplayMode, HTMLButtonElement>();
  const modes: Array<[StageDisplayMode, string]> = [
    ['normal', options.labels.normal],
    ['expand', options.labels.expand],
    ['maximize', options.labels.maximize],
  ];
  for (const [mode, label] of modes) {
    const button = documentRef.createElement('button');
    button.type = 'button';
    button.className = 'result-button result-button-small';
    button.textContent = label;
    button.setAttribute('aria-pressed', String(mode === 'normal'));
    button.addEventListener('click', () => { void controller.setMode(mode); });
    group.append(button);
    buttons.set(mode, button);
  }
  const unsubscribe = controller.onChange((mode) => {
    for (const [id, button] of buttons) button.setAttribute('aria-pressed', String(id === mode));
  });
  options.container.append(group);
  return {
    element: group,
    controller,
    destroy: () => { unsubscribe(); controller.destroy(); group.remove?.(); },
  };
}
