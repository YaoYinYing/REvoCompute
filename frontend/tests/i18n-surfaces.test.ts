import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { applyLocale, translate } from '../src/app/i18n';
import { parseWorkspaceDescriptor, PayloadFault } from '../src/features/create-task/api';
import { PluginHost } from '../src/features/create-task/input-workspace/PluginHost';
import { validateParameter } from '../src/features/create-task/parameter-controls';
import type { ParameterDefinition } from '../src/features/create-task/types';
import { createBasicRenderers } from '../src/features/results/renderer-registry';

/*
 * The §11 internationalization boundary, exercised on the rendered surfaces.
 *
 * Each changed feature is driven through the smallest DOM its component uses, so
 * the assertion is on what the user reads: an app-owned label follows the locale,
 * while a server-projected scientific value is emitted verbatim in both locales.
 * `i18n.test.ts` owns catalog parity; here the point is the boundary itself.
 */

class FakeElement {
  className = '';
  innerHTML = '';
  hidden = false;
  id = '';
  value = '';
  checked = false;
  textContent = '';
  readonly style: Record<string, string> = {};
  readonly dataset: Record<string, string> = {};
  readonly children: FakeElement[] = [];
  readonly attributes: Record<string, string> = {};
  parentElement: FakeElement | null = null;
  private readonly bySelector = new Map<string, FakeElement>();
  readonly classList = {
    add: (): void => undefined,
    remove: (): void => undefined,
    toggle: (): void => undefined,
    contains: (): boolean => false,
  };
  constructor(readonly tagName: string) {}
  append(...nodes: FakeElement[]): void {
    for (const node of nodes) { node.parentElement = this; this.children.push(node); }
  }
  prepend(...nodes: FakeElement[]): void {
    for (const node of nodes.reverse()) { node.parentElement = this; this.children.unshift(node); }
  }
  replaceChildren(...nodes: FakeElement[]): void {
    this.children.length = 0;
    this.append(...nodes);
  }
  remove(): void {
    const parent = this.parentElement;
    if (parent) parent.children.splice(parent.children.indexOf(this), 1);
    this.parentElement = null;
  }
  setAttribute(name: string, value: string): void { this.attributes[name] = String(value); }
  getAttribute(name: string): string | null { return this.attributes[name] ?? null; }
  removeAttribute(name: string): void { delete this.attributes[name]; }
  toggleAttribute(name: string, force?: boolean): void { if (force) this.setAttribute(name, ''); else this.removeAttribute(name); }
  addEventListener(): void {}
  removeEventListener(): void {}
  dispatchEvent(): boolean { return true; }
  setSelectionRange(): void {}
  focus(): void {}
  /** The smallest selector surface the driven components actually use. */
  querySelector<T = FakeElement>(selector: string): T | null {
    let node = this.bySelector.get(selector);
    if (!node) { node = new FakeElement(selector.replace(/[^a-z]/gi, '') || 'div'); this.bySelector.set(selector, node); }
    return node as unknown as T;
  }
  querySelectorAll<T = FakeElement>(): T[] { return []; }
  closest(): FakeElement | null { return null; }
}

class FakeOption extends FakeElement {
  constructor(readonly text: string, readonly value: string) { super('option'); }
}

function installDom(): void {
  vi.stubGlobal('Option', FakeOption);
  vi.stubGlobal('document', {
    documentElement: { dataset: {}, lang: '', style: {} },
    body: new FakeElement('body'),
    head: new FakeElement('head'),
    createElement: (tag: string) => new FakeElement(tag),
    createElementNS: (_ns: string, tag: string) => new FakeElement(tag),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  });
  vi.stubGlobal('localStorage', {
    getItem: () => null, setItem: () => undefined, removeItem: () => undefined, clear: () => undefined,
    key: () => null, get length() { return 0; },
  });
  vi.stubGlobal('navigator', { language: 'en-US' });
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }));
}

beforeEach(() => { installDom(); });
afterEach(() => { applyLocale('en', false); vi.unstubAllGlobals(); });

describe('§11 boundary on the Create Task workbench', () => {
  it('localizes the validation frame but keeps the server parameter label verbatim', () => {
    applyLocale('zh-CN');
    const parameter = {
      name: 'msa_depth', type: 'int', label: 'MSA depth', required: true,
      description: '', help: '', unit: '', defaultValue: undefined, choices: [], advanced: false,
    } as unknown as ParameterDefinition;
    const control = { value: '', checkValidity: () => true, validationMessage: '' } as unknown as HTMLInputElement;

    const message = validateParameter(parameter, control);
    // The template frame is frontend-owned and localized...
    expect(message).toBe('MSA depth 为必填项。');
    // ...while the interpolated server parameter label is emitted verbatim.
    expect(message).toContain('MSA depth');
    expect(message).not.toBe(translate('en', 'ct.param.required', { label: parameter.label }));
  });

  it('localizes the component-failure notice rendered by the workspace host', () => {
    applyLocale('zh-CN');
    const host = new PluginHost([{ id: 'structure', mount: () => { throw new Error('viewer unavailable'); } }], { fetch });
    const target = new FakeElement('div');
    host.mount(
      [{ plugin: 'structure', id: 'structure', title: 'Structure', options: {}, stepId: 'inputs' }],
      {} as never,
      () => target as unknown as HTMLElement,
    );
    const notice = target.children[0]!;
    expect(notice.textContent).toBe('此组件无法加载：viewer unavailable');
    expect(notice.textContent).not.toBe(translate('en', 'ct.componentFailed', { message: 'viewer unavailable' }));
  });

  it('localizes an unmounted-capability notice while the server-projected plugin id stays verbatim', () => {
    applyLocale('zh-CN');
    const host = new PluginHost([], { fetch });
    const plugin = 'unavailable_fixture_plugin';
    host.mount(
      [{ plugin, id: 'regions', title: 'Regions', options: {}, stepId: 'inputs' }],
      {} as never,
      () => new FakeElement('div') as unknown as HTMLElement,
    );
    const [unknown] = host.unknownComponents();
    // The sentence frame is frontend-owned and localized...
    expect(unknown!.message).toBe('unavailable_fixture_plugin：不支持的组件');
    expect(unknown!.message).not.toBe(translate('en', 'ct.componentUnavailable', { plugin }));
    expect(unknown!.message).not.toContain('unsupported component');
    // ...while the plugin id the server's workspace contract declared is emitted verbatim.
    expect(unknown!.message).toContain(plugin);
    // The stable internal signal the workbench keys on is the plugin id, so the
    // workspace-failure rule never depends on the user-facing language.
    expect(host.unknownComponents().map(item => item.plugin)).toEqual([plugin]);
  });

  it('localizes a workspace contract fault without depending on the user-facing language', () => {
    applyLocale('zh-CN');
    vi.stubGlobal('window', { location: { origin: 'https://compute.example' } });
    const fault = (): PayloadFault => {
      try {
        parseWorkspaceDescriptor({
          id: 'regions', owner: 'runner', global_id: 'runner:regions',
          descriptor_url: 'https://evil.example/plugins/runner/regions',
          module: { url: '/compute/api/workspace/assets/runner/regions/index.js', type: 'module' }, stylesheets: [],
        });
      } catch (error) { return error as PayloadFault; }
      throw new Error('the descriptor was expected to be rejected');
    };
    // The fault frame is frontend-owned and localized.
    expect(fault().message).toBe('工作区插件描述符地址无效。');
    expect(fault().message).not.toBe(translate('en', 'ct.payload.fault.invalid', { field: translate('en', 'ct.payload.field.descriptorUrl') }));
    // The stable signal a caller can match on is the fault type, not its prose.
    expect(fault()).toBeInstanceOf(PayloadFault);
  });
});

describe('§11 boundary on the Result workspace', () => {
  it('localizes the download-only notice while the declared table vocabulary stays verbatim', async () => {
    applyLocale('zh-CN');
    const renderers = createBasicRenderers();

    const downloadOnly = renderers.find(candidate => candidate.id === 'download_only')!;
    const host = new FakeElement('div');
    await downloadOnly.render(
      { path: 'readme.txt', size: 1, sha256: 'a'.repeat(64), url: '/a', media_type: 'text/plain', preview: null, role: 'artifact' } as never,
      host as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32) },
    );
    expect(host.children[0]!.textContent).toBe('没有可用的内联预览。该文件仍可下载。');

    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      columns: ['score'], rows: [[1]], has_more: true,
    }))));
    const table = renderers.find(candidate => candidate.id === 'table')!;
    const tableHost = new FakeElement('div');
    await table.render(
      { path: 'scores.csv', size: 8, sha256: 'b'.repeat(64), url: '/t', table_url: '/authorized/table/scores', media_type: 'text/csv', preview: 'table', role: 'evidence' } as never,
      tableHost as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32) },
    );
    // The truncation note is frontend-authored and localized.
    expect(tableHost.children.some(node => node.textContent === '仅显示前 100 行。')).toBe(true);
    // A server-declared column heading is emitted verbatim, not translated.
    const header = tableHost.children[0]!.children[0]!.children[0]!;
    expect(header.children[0]!.textContent).toBe('score');
  });
});
