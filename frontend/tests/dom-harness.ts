import type { Mock } from 'vitest';

/*
 * A small DOM for component tests that drive real elements.
 *
 * The repository ships no browser DOM for vitest (jsdom/happy-dom are absent, and
 * the shared install must not gain one), so a test that exercises a real component
 * builds the tree against this harness and asserts on what it renders: creation,
 * a markup parser for `innerHTML`, document order, and the selector queries the
 * components use. `children` holds elements only and `childNodes` holds every node,
 * as in the browser, so a component's own traversal behaves as it does in product.
 */

export class HarnessNode {
  parent: HarnessNode | null = null;
  nodes: HarnessNode[] = [];
  ownText = '';
  checked = false;
  private attrs = new Map<string, string>();
  private listeners = new Map<string, Array<(event: never) => void>>();
  readonly tag: string;

  constructor(tag: string) { this.tag = tag.toUpperCase(); }

  // -- identity ------------------------------------------------------------
  get tagName(): string { return this.tag; }
  get nodeName(): string { return this.tag; }
  get nodeType(): number { return this.tag === '#TEXT' ? 3 : 1; }
  get parentNode(): HarnessNode | null { return this.parent; }
  get ownerDocument(): unknown { return harnessDocument; }
  get isConnected(): boolean { return true; }

  get id(): string { return this.getAttribute('id') ?? ''; }
  set id(value: string) { this.setAttribute('id', value); }
  get className(): string { return this.getAttribute('class') ?? ''; }
  set className(value: string) { this.setAttribute('class', value); }

  get dataset(): Record<string, string> { return this.datasetProxy; }

  get classList() {
    const names = (): string[] => this.className.split(/\s+/).filter(Boolean);
    const write = (list: string[]): void => { this.className = [...new Set(list)].join(' '); };
    return {
      add: (...tokens: string[]) => write([...names(), ...tokens]),
      remove: (...tokens: string[]) => write(names().filter(name => !tokens.includes(name))),
      contains: (token: string) => names().includes(token),
      toggle: (token: string, force?: boolean) => { const on = force ?? !names().includes(token); write(on ? [...names(), token] : names().filter(name => name !== token)); return on; },
    };
  }

  readonly style = { setProperty: (): void => undefined };
  // A live view of the `data-*` attributes, as `dataset` is in the browser.
  private readonly datasetProxy = new Proxy({} as Record<string, string>, {
    get: (_target, property: string) => this.attrs.get(`data-${property.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`),
    set: (_target, property: string, value: unknown) => {
      this.attrs.set(`data-${property.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`, String(value));
      return true;
    },
    has: (_target, property: string) => this.attrs.has(`data-${property.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`),
    ownKeys: () => [...this.attrs.keys()].filter(name => name.startsWith('data-')),
    getOwnPropertyDescriptor: (_target, property: string) => {
      const key = `data-${property.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`;
      return this.attrs.has(key) ? { configurable: true, enumerable: true, value: this.attrs.get(key) } : undefined;
    },
  });
  get attributes(): Array<{ name: string; value: string }> { return [...this.attrs].map(([name, value]) => ({ name, value })); }

  getAttribute(name: string): string | null { return this.attrs.get(name) ?? null; }
  setAttribute(name: string, value: string): void { this.attrs.set(name, String(value)); }
  hasAttribute(name: string): boolean { return this.attrs.has(name); }
  removeAttribute(name: string): void { this.attrs.delete(name); }

  get hidden(): boolean { return this.hasAttribute('hidden'); }
  set hidden(value: boolean) { value ? this.setAttribute('hidden', '') : this.removeAttribute('hidden'); }
  get disabled(): boolean { return this.hasAttribute('disabled'); }
  set disabled(value: boolean) { value ? this.setAttribute('disabled', '') : this.removeAttribute('disabled'); }
  get title(): string { return this.getAttribute('title') ?? ''; }
  set title(value: string) { this.setAttribute('title', value); }
  get href(): string { return this.getAttribute('href') ?? ''; }
  set href(value: string) { this.setAttribute('href', value); }
  get type(): string { return this.getAttribute('type') ?? ''; }
  set type(value: string) { this.setAttribute('type', value); }

  // -- content -------------------------------------------------------------
  set textContent(value: string) { this.nodes = []; this.ownText = value; }
  get textContent(): string { return this.ownText + this.nodes.map(node => node.textContent).join(''); }
  set innerHTML(html: string) { this.nodes = []; this.ownText = ''; parseMarkup(this, html); }
  get innerHTML(): string { return this.outerHTML; }
  get outerHTML(): string {
    const attrs = this.attributes.map(({ name, value }) => (value === '' ? ` ${name}` : ` ${name}="${value}"`)).join('');
    return `<${this.tag.toLowerCase()}${attrs}>${this.ownText}${this.nodes.map(node => node.outerHTML).join('')}</${this.tag.toLowerCase()}>`;
  }

  // -- tree ----------------------------------------------------------------
  get childNodes(): HarnessNode[] { return this.nodes; }
  get children(): HarnessNode[] { return this.nodes.filter(node => node.nodeType === 1); }
  get firstChild(): HarnessNode | null { return this.nodes[0] ?? null; }
  get lastChild(): HarnessNode | null { return this.nodes[this.nodes.length - 1] ?? null; }
  get firstElementChild(): HarnessNode | null { return this.children[0] ?? null; }
  get nextSibling(): HarnessNode | null {
    const siblings = this.parent?.nodes ?? [];
    return siblings[siblings.indexOf(this) + 1] ?? null;
  }

  append(...nodes: Array<HarnessNode | string>): this {
    for (const node of nodes) {
      const child = typeof node === 'string' ? textNode(node) : node;
      child.remove();
      child.parent = this;
      this.nodes.push(child);
    }
    return this;
  }
  appendChild(node: HarnessNode): HarnessNode { this.append(node); return node; }
  prepend(...nodes: Array<HarnessNode | string>): this { const existing = this.nodes; this.nodes = []; return this.append(...nodes, ...existing); }
  replaceChildren(...nodes: Array<HarnessNode | string>): void { this.nodes = []; this.append(...nodes); }
  insertBefore(node: HarnessNode, reference: HarnessNode | null): HarnessNode {
    node.remove();
    node.parent = this;
    const index = reference ? this.nodes.indexOf(reference) : -1;
    if (index === -1) this.nodes.push(node); else this.nodes.splice(index, 0, node);
    return node;
  }
  replaceChild(next: HarnessNode, previous: HarnessNode): void {
    const index = this.nodes.indexOf(previous);
    if (index === -1) return;
    next.parent = this;
    this.nodes[index] = next;
  }
  remove(): void {
    const siblings = this.parent?.nodes;
    if (!siblings) return;
    siblings.splice(siblings.indexOf(this), 1);
    this.parent = null;
  }
  removeChild(node: HarnessNode): void { node.remove(); }
  contains(node: HarnessNode): boolean { return node === this || this.nodes.some(child => child.contains(node)); }
  getBoundingClientRect(): { width: number; height: number } { return { width: 0, height: 0 }; }
  focus(): void {}
  scrollIntoView(): void {}
  closest(selector: string): HarnessNode | null {
    for (let node: HarnessNode | null = this; node; node = node.parent) if (matches(node, selector)) return node;
    return null;
  }

  addEventListener(type: string, listener: (event: never) => void): void { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  removeEventListener(type: string, listener: (event: never) => void): void { this.listeners.set(type, (this.listeners.get(type) ?? []).filter(item => item !== listener)); }
  dispatch(type: string, event: unknown): void { for (const listener of this.listeners.get(type) ?? []) listener(event as never); }

  // -- queries -------------------------------------------------------------
  querySelector(selector: string): HarnessNode | null { return this.querySelectorAll(selector)[0] ?? null; }
  querySelectorAll(selector: string): HarnessNode[] {
    const found: HarnessNode[] = [];
    for (const group of selector.split(',')) {
      const steps = group.trim().split(/\s+/).filter(Boolean);
      if (!steps.length) continue;
      let roots: HarnessNode[] = [this];
      for (const [index, step] of steps.entries()) {
        const hits = roots.flatMap(root => descendants(root).filter(node => matches(node, step)));
        if (index === steps.length - 1) { for (const hit of hits) if (!found.includes(hit)) found.push(hit); break; }
        roots = hits;
      }
    }
    return found;
  }
}

/** Element descendants in document order, excluding the node itself. */
export function descendants(node: HarnessNode): HarnessNode[] {
  const out: HarnessNode[] = [];
  for (const child of node.nodes) {
    if (child.nodeType === 1) out.push(child);
    out.push(...descendants(child));
  }
  return out;
}

/** The node and its element descendants, in document order. */
export function documentOrder(root: HarnessNode): HarnessNode[] {
  return root.nodeType === 1 ? [root, ...descendants(root)] : descendants(root);
}

export function textNode(value: string): HarnessNode { const node = new HarnessNode('#TEXT'); node.ownText = value; return node; }

const VOID_TAGS = new Set(['INPUT', 'IMG', 'BR', 'HR', 'META', 'LINK']);
const RAWTEXT_TAGS = new Set(['SCRIPT', 'STYLE']);

/** Parse well-formed markup — tags, quoted attributes, void elements — into `host`. */
function parseMarkup(host: HarnessNode, html: string): void {
  const token = /<(\/?)([a-zA-Z][\w:-]*)((?:\s+[\w:-]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*(\/?)>|([^<]+)/g;
  const stack: HarnessNode[] = [host];
  let match: RegExpExecArray | null;
  while ((match = token.exec(html)) !== null) {
    const [, closing, tag, attributeText, selfClosing, text] = match;
    const top = stack[stack.length - 1]!;
    if (text !== undefined) { if (!RAWTEXT_TAGS.has(top.tag)) top.append(text); continue; }
    if (closing) { if (stack.length > 1) stack.pop(); continue; }
    const node = new HarnessNode(tag!);
    for (const attribute of (attributeText ?? '').matchAll(/([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g)) {
      node.setAttribute(attribute[1]!, attribute[2] ?? attribute[3] ?? attribute[4] ?? '');
    }
    top.append(node);
    if (!selfClosing && !VOID_TAGS.has(node.tag)) stack.push(node);
  }
}

/** One compound selector: tag, #id, .class, and [attr] / [attr="value"]. */
function matches(node: HarnessNode, selector: string): boolean {
  const parsed = /^([a-zA-Z][\w-]*)?(#[\w-]+)?((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$/.exec(selector.trim());
  if (!parsed) return false;
  const [, tag, id, classes, attributes] = parsed;
  if (tag && node.tag !== tag.toUpperCase()) return false;
  if (id && node.id !== id.slice(1)) return false;
  for (const name of (classes ?? '').split('.').filter(Boolean)) if (!node.classList.contains(name)) return false;
  for (const attribute of (attributes ?? '').matchAll(/\[([\w-]+)(?:=["']?([^"'\]]*)["']?)?\]/g)) {
    if (!node.hasAttribute(attribute[1]!)) return false;
    if (attribute[2] !== undefined && node.getAttribute(attribute[1]!) !== attribute[2]) return false;
  }
  return true;
}

/** The document surface the components build against. */
export const harnessDocument = {
  createElement: (tag: string): HarnessNode => new HarnessNode(tag),
  createElementNS: (_namespace: string, tag: string): HarnessNode => new HarnessNode(tag),
  createTextNode: textNode,
  documentElement: new HarnessNode('HTML'),
  body: new HarnessNode('BODY'),
  head: new HarnessNode('HEAD'),
  querySelectorAll: (): HarnessNode[] => [],
  addEventListener: (): void => {},
};

export interface HarnessOptions {
  /** Pathname the components read from `location`. */
  pathname?: string;
  /** Whether `matchMedia(query)` reports a match (drives width-dependent chrome). */
  matches?: boolean;
  /** Locale the components resolve for frontend-owned copy. */
  locale?: string;
}

/** Install the document and browser globals the shell and Dashboard read. */
export function installHarness(stubGlobal: Mock | ((name: string, value: unknown) => void), options: HarnessOptions = {}): void {
  harnessDocument.documentElement = new HarnessNode('HTML');
  harnessDocument.body = new HarnessNode('BODY');
  harnessDocument.head = new HarnessNode('HEAD');
  const storage = new Map<string, string>();
  const location = { pathname: options.pathname ?? '/compute/dashboard', origin: 'https://revocompute.invalid', assign: (): void => {}, reload: (): void => {} };
  const mediaQuery = () => ({ matches: options.matches ?? false, addEventListener: (): void => {}, removeEventListener: (): void => {} });
  const globals: Record<string, unknown> = {
    document: harnessDocument,
    window: { location, matchMedia: mediaQuery, innerWidth: 1280, innerHeight: 900, addEventListener: (): void => {}, removeEventListener: (): void => {}, dispatchEvent: (): boolean => true, setTimeout: (): number => 0, clearTimeout: (): void => {} },
    location,
    navigator: { language: options.locale ?? 'en' },
    localStorage: { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => { storage.set(key, String(value)); }, removeItem: (key: string) => { storage.delete(key); }, clear: () => storage.clear() },
    matchMedia: mediaQuery,
    ResizeObserver: class { observe(): void {} disconnect(): void {} unobserve(): void {} },
    Node: HarnessNode,
    HTMLInputElement: class {},
    Event: class { constructor(readonly type: string) {} },
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
  };
  for (const [name, value] of Object.entries(globals)) stubGlobal(name, value);
}
