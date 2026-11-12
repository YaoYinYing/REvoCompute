import { describe, expect, it, vi } from 'vitest';

import {
  DisplayModeController,
  canUseFullscreen,
  createDisplayModeControls,
  maximizeSupport,
  normalizeDisplayMode,
} from '../src/features/structure/display-mode';

class FakeElement {
  readonly tag: string;
  className = '';
  textContent = '';
  title = '';
  type = '';
  readonly dataset: Record<string, string> = {};
  readonly children: FakeElement[] = [];
  parent: FakeElement | null = null;
  focused = false;
  private attributes = new Map<string, string>();
  private listeners = new Map<string, Array<(event: never) => void>>();
  constructor(tag: string) { this.tag = tag; }
  setAttribute(name: string, value: string): void { this.attributes.set(name, String(value)); }
  getAttribute(name: string): string | null { return this.attributes.get(name) ?? null; }
  removeAttribute(name: string): void { this.attributes.delete(name); }
  hasAttribute(name: string): boolean { return this.attributes.has(name); }
  append(...nodes: FakeElement[]): void { for (const node of nodes) { node.parent = this; this.children.push(node); } }
  remove(): void {
    if (!this.parent) return;
    this.parent.children.splice(this.parent.children.indexOf(this), 1);
    this.parent = null;
  }
  addEventListener(type: string, listener: (event: never) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  removeEventListener(type: string, listener: (event: never) => void): void {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter(entry => entry !== listener));
  }
  dispatch(type: string, event: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) (listener as (value: unknown) => void)(event);
  }
  querySelectorAll(): FakeElement[] { return []; }
  focus(): void { doc.activeElement = this; this.focused = true; }
  requestFullscreen?: () => Promise<void>;
}

interface FakeDocument {
  fullscreenEnabled: boolean;
  fullscreenElement: FakeElement | null;
  activeElement: FakeElement | null;
  body: FakeElement;
  exitFullscreen: ReturnType<typeof vi.fn>;
  createElement(tag: string): FakeElement;
  addEventListener(type: string, listener: (event: never) => void): void;
  removeEventListener(type: string, listener: (event: never) => void): void;
  dispatch(type: string, event?: unknown): void;
}

let doc: FakeDocument;

function fakeDocument(fullscreen = false): FakeDocument {
  const listeners = new Map<string, Array<(event: never) => void>>();
  const document: FakeDocument = {
    fullscreenEnabled: fullscreen,
    fullscreenElement: null,
    activeElement: null,
    body: new FakeElement('body'),
    exitFullscreen: vi.fn(async () => { document.fullscreenElement = null; }),
    createElement: (tag) => new FakeElement(tag),
    addEventListener: (type, listener) => listeners.set(type, [...(listeners.get(type) ?? []), listener]),
    removeEventListener: (type, listener) => listeners.set(type, (listeners.get(type) ?? []).filter(entry => entry !== listener)),
    dispatch: (type, event) => { for (const listener of listeners.get(type) ?? []) (listener as (value: unknown) => void)(event); },
  };
  return document;
}

const labels = {
  group: 'Stage display mode',
  normal: 'Normal',
  expand: 'Expand',
  maximize: 'Maximize',
  fullscreenFallback: 'Fullscreen is unavailable',
  enterFullscreen: 'Enter fullscreen',
  exitFullscreen: 'Exit fullscreen',
  expanded: 'Expanded',
  maximized: 'Maximized',
  collapsed: 'Collapsed',
};

function stage(fullscreen = false): FakeElement {
  const element = new FakeElement('section');
  if (fullscreen) {
    element.requestFullscreen = async () => { doc.fullscreenElement = element; doc.dispatch('fullscreenchange'); };
  }
  return element;
}

function controllerFor(element: FakeElement, options: { fullscreen?: boolean } = {}): DisplayModeController {
  doc = fakeDocument(options.fullscreen ?? false);
  return new DisplayModeController({
    stage: element as unknown as HTMLElement,
    resize: () => undefined,
    labels,
    document: doc as unknown as Document,
    requestFrame: (callback) => { callback(); return 0; },
  });
}

describe('display mode decisions', () => {
  it('normalizes unknown values to normal', () => {
    expect(normalizeDisplayMode('expand')).toBe('expand');
    expect(normalizeDisplayMode('maximize')).toBe('maximize');
    expect(normalizeDisplayMode('fullscreen')).toBe('normal');
    expect(normalizeDisplayMode(undefined)).toBe('normal');
  });

  it('uses native fullscreen only where the document enables it', () => {
    expect(canUseFullscreen({ fullscreenEnabled: true } as never)).toBe(true);
    expect(canUseFullscreen({ fullscreenEnabled: false } as never)).toBe(false);
    expect(canUseFullscreen(null)).toBe(false);
    expect(maximizeSupport({ fullscreenEnabled: false } as never)).toEqual({ fallback: true });
    expect(maximizeSupport({ fullscreenEnabled: true } as never)).toEqual({ fallback: false });
  });
});

describe('display mode controller lifecycle', () => {
  it('expands the same stage without reparenting it and restores focus on Escape', async () => {
    const element = stage();
    const controller = controllerFor(element);
    const trigger = new FakeElement('button');
    doc.activeElement = trigger;

    await controller.setMode('expand');
    expect(controller.mode()).toBe('expand');
    expect(element.dataset.displayMode).toBe('expand');
    expect(element.getAttribute('role')).toBe('dialog');
    expect(element.getAttribute('aria-modal')).toBe('true');
    expect(element.children.some(child => child.className.startsWith('structure-mode-status'))).toBe(true);
    expect(doc.body.children.some(child => child.className === 'structure-mode-backdrop')).toBe(true);
    expect(element.parent).toBeNull();

    doc.dispatch('keydown', { key: 'Escape', preventDefault: () => undefined });
    await Promise.resolve();
    expect(controller.mode()).toBe('normal');
    expect(element.dataset.displayMode).toBeUndefined();
    expect(element.getAttribute('role')).toBeNull();
    expect(doc.body.children.some(child => child.className === 'structure-mode-backdrop')).toBe(false);
    expect(doc.activeElement).toBe(trigger);
    controller.destroy();
  });

  it('labels and shows the expand overlay when native fullscreen is unavailable', async () => {
    const element = stage(false);
    const controller = controllerFor(element, { fullscreen: false });
    await controller.setMode('maximize');
    expect(controller.mode()).toBe('maximize');
    expect(element.dataset.displayMode).toBe('maximize');
    expect(element.dataset.fullscreenFallback).toBe('true');
    expect(element.children.some(child => child.className.startsWith('structure-mode-status') && child.textContent === labels.fullscreenFallback)).toBe(true);
    controller.destroy();
    expect(element.dataset.displayMode).toBeUndefined();
    expect(element.dataset.fullscreenFallback).toBeUndefined();
  });

  it('uses native fullscreen when available and exits it when returning to normal', async () => {
    const element = stage(true);
    const controller = controllerFor(element, { fullscreen: true });
    await controller.setMode('maximize');
    expect(controller.mode()).toBe('maximize');
    expect(doc.fullscreenElement).toBe(element);
    expect(element.dataset.fullscreenFallback).toBeUndefined();
    await controller.setMode('normal');
    expect(controller.mode()).toBe('normal');
    expect(doc.exitFullscreen).toHaveBeenCalled();
    controller.destroy();
  });

  it('disposes exactly once', async () => {
    const element = stage();
    const controller = controllerFor(element);
    await controller.setMode('expand');
    controller.destroy();
    controller.destroy();
    expect(element.dataset.displayMode).toBeUndefined();
    expect(doc.body.children).toHaveLength(0);
  });

  it('keeps the pre-existing accessible fullscreen name on the maximize control', async () => {
    const element = stage(true);
    doc = fakeDocument(true);
    const container = new FakeElement('div');
    const controls = createDisplayModeControls({
      stage: element as unknown as HTMLElement,
      container: container as unknown as HTMLElement,
      resize: () => undefined,
      labels,
      document: doc as unknown as Document,
      requestFrame: (callback) => { callback(); return 0; },
    });
    const button = (controls.element as unknown as FakeElement).children.find(child => child.textContent === labels.maximize)!;
    expect(button.getAttribute('aria-label')).toBe(labels.enterFullscreen);
    expect(button.title).toBe(labels.enterFullscreen);

    button.dispatch('click', {});
    await vi.waitFor(() => expect(doc.fullscreenElement).toBe(element));
    await vi.waitFor(() => expect(button.getAttribute('aria-label')).toBe(labels.exitFullscreen));
    expect(button.title).toBe(labels.exitFullscreen);

    button.dispatch('click', {});
    await vi.waitFor(() => expect(doc.fullscreenElement).toBeNull());
    await vi.waitFor(() => expect(button.getAttribute('aria-label')).toBe(labels.enterFullscreen));
    expect(button.title).toBe(labels.enterFullscreen);
    controls.destroy();
  });
});
