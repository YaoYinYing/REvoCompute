import type { ResultFile } from '../../api/result-types';

const MAX_ELEMENTS = 1_048_576;

export interface NumericProjection {
  dtype: string;
  shape: number[];
  key: string | null;
  totalElements: number;
  values: Array<number | null>;
}
export interface CategoricalProjection extends Omit<NumericProjection, 'values'> { values: string[]; }

export async function loadProjection(
  artifact: Pick<ResultFile, 'ndarray_url'>,
  options: { key?: string; signal?: AbortSignal; maxElements?: number; kind?: 'numeric' | 'categorical' } = {},
): Promise<NumericProjection | CategoricalProjection> {
  if (!artifact.ndarray_url) throw new TypeError('The artifact has no bounded projection URL.');
  const maximum = options.maxElements ?? MAX_ELEMENTS, kind = options.kind ?? 'numeric';
  if (!Number.isInteger(maximum) || maximum < 1 || maximum > MAX_ELEMENTS) throw new RangeError('Projection limits are invalid.');
  const query = new URLSearchParams({ max_elements: String(maximum) }); if (kind === 'categorical') query.set('kind', kind);
  if (options.key != null) query.set('key', options.key);
  const separator = artifact.ndarray_url.includes('?') ? '&' : '?';
  const response = await fetch(`${artifact.ndarray_url}${separator}${query}`, { credentials: 'same-origin', signal: options.signal });
  if (!response.ok) { const error = new Error('The bounded projection could not be loaded.') as Error & { status?: number }; error.status = response.status; throw error; }
  const projection = await response.json() as { kind: string; dtype: string; shape: number[]; key: string | null; total_elements: number; data: unknown[] };
  const shapeTotal = Array.isArray(projection.shape)
    ? projection.shape.reduce((product, size) => Number.isInteger(size) && size >= 0 ? product * size : Number.NaN, 1)
    : Number.NaN;
  const validValues = kind === 'numeric'
    ? Array.isArray(projection.data) && projection.data.every((value) => value === null || Number.isFinite(Number(value)))
    : Array.isArray(projection.data) && projection.data.every((value) => typeof value === 'string');
  if (projection.kind !== kind || !Number.isInteger(projection.total_elements) || projection.total_elements < 0 || projection.total_elements > maximum ||
      shapeTotal !== projection.total_elements || projection.data.length !== projection.total_elements || !validValues) {
    throw new Error('The bounded projection is invalid or exceeds browser limits.');
  }
  return { dtype: projection.dtype, shape: [...projection.shape], key: projection.key, totalElements: projection.total_elements,
    values: kind === 'numeric' ? projection.data.map((value) => value === null ? null : Number(value)) : projection.data as string[] } as NumericProjection | CategoricalProjection;
}

export async function loadNumericProjection(
  artifact: Pick<ResultFile, 'ndarray_url'>,
  options: { key?: string; signal?: AbortSignal; maxElements?: number } = {},
): Promise<NumericProjection> {
  return loadProjection(artifact, { ...options, kind: 'numeric' }) as Promise<NumericProjection>;
}

export interface SelectionState { candidate: string | number | null; entityA: string | null; entityB: string | null; token: number | null }
export class ResultSelectionStore {
  private state: SelectionState;
  private readonly listeners = new Set<(state: Readonly<SelectionState>, source: unknown) => void>();
  constructor(initial: Partial<SelectionState> = {}) {
    this.state = { candidate: null, entityA: null, entityB: null, token: null, ...initial };
  }
  get(): Readonly<SelectionState> { return Object.freeze({ ...this.state }); }
  set(patch: Partial<SelectionState>, source: unknown = null): Readonly<SelectionState> {
    const next = { ...this.state, ...patch };
    if (Object.keys(next).every((key) => next[key as keyof SelectionState] === this.state[key as keyof SelectionState])) return this.get();
    this.state = next; const snapshot = this.get(); this.listeners.forEach((listener) => listener(snapshot, source)); return snapshot;
  }
  subscribe(listener: (state: Readonly<SelectionState>, source: unknown) => void): () => void {
    this.listeners.add(listener); return () => this.listeners.delete(listener);
  }
  destroy(): void { this.listeners.clear(); }
}

export class CandidateSelector<T extends { id?: string | number }> {
  private generation = 0;
  private controller: AbortController | null = null;
  constructor(private readonly host: HTMLElement, private readonly options: {
    items: T[]; label?: (item: T, index: number) => string; buttonClass?: string;
    store?: ResultSelectionStore; onSelect: (item: T, index: number, request: { signal: AbortSignal; current(): boolean }) => Promise<unknown> | unknown;
  }) { this.render(); }
  private render(): void {
    this.host.replaceChildren(); this.options.items.forEach((item, index) => {
      const button = document.createElement('button'); button.type = 'button'; button.dataset.index = String(index);
      button.className = this.options.buttonClass || 'candidate-open'; button.setAttribute('aria-current', 'false');
      button.textContent = this.options.label?.(item, index) || String(item.id ?? index + 1);
      button.addEventListener('click', () => { void this.select(index); }); this.host.append(button);
    });
  }
  async select(index: number): Promise<unknown> {
    const item = this.options.items[index]; if (!item) return null;
    this.controller?.abort(); this.controller = new AbortController(); const generation = ++this.generation;
    const result = await this.options.onSelect(item, index, {
      signal: this.controller.signal, current: () => generation === this.generation,
    });
    if (generation !== this.generation) return null;
    this.host.querySelectorAll<HTMLElement>('[data-index]').forEach((button) => button.setAttribute('aria-current', button.dataset.index === String(index) ? 'true' : 'false'));
    this.options.store?.set({ candidate: item.id ?? index }, this); return result;
  }
  destroy(): void { this.generation += 1; this.controller?.abort(); this.host.replaceChildren(); }
}

export class ScalarMetricGrid {
  constructor(private readonly host: HTMLElement, metrics: Array<{ label: string; value: unknown; unit?: string; meaning?: string; nullable?: boolean }>) { this.update(metrics); }
  update(metrics: Array<{ label: string; value: unknown; unit?: string; meaning?: string; nullable?: boolean }>): void {
    const list = document.createElement('dl'); list.className = 'scalar-grid';
    metrics.forEach((metric) => { if (metric.value == null && !metric.nullable) return;
      const term = document.createElement('dt'); term.textContent = metric.label; const value = document.createElement('dd');
      value.textContent = metric.value == null ? 'N/A' : `${String(metric.value)}${metric.unit ? ` ${metric.unit}` : ''}`;
      if (metric.meaning) { const meaning = document.createElement('span'); meaning.textContent = metric.meaning; value.append(meaning); }
      list.append(term, value);
    }); this.host.replaceChildren(list);
  }
  destroy(): void { this.host.replaceChildren(); }
}

type PrimitiveViewer = Record<string, (...arguments_: any[]) => unknown> & { mount?: (host: HTMLElement, options: unknown) => unknown; resize?: () => void; dispose?: () => void };
export class StructureViewport {
  readonly root: HTMLElement;
  readonly viewerHost: HTMLElement;
  readonly ready: Promise<PrimitiveViewer>;
  private viewer: PrimitiveViewer | null;
  private observer: ResizeObserver | null = null;
  private destroyed = false;
  constructor(private readonly host: HTMLElement, options: { viewer?: PrimitiveViewer; createViewer?: () => PrimitiveViewer | Promise<PrimitiveViewer>; toolbar?: HTMLElement; viewerOptions?: unknown }) {
    if (!options.viewer && !options.createViewer) throw new TypeError('StructureViewport requires a viewer or createViewer function.');
    this.viewer = options.viewer || null; this.root = document.createElement('div'); this.root.className = 'structure-viewport';
    this.viewerHost = document.createElement('div'); this.viewerHost.className = 'structure-viewport-host'; if (options.toolbar) this.root.append(options.toolbar); this.root.append(this.viewerHost); host.replaceChildren(this.root);
    this.ready = Promise.resolve(this.viewer || options.createViewer!()).then(async (viewer) => { this.viewer = viewer; if (viewer.mount) await viewer.mount(this.viewerHost, options.viewerOptions || {}); return viewer; });
    if (typeof ResizeObserver !== 'undefined') { this.observer = new ResizeObserver(() => this.viewer?.resize?.()); this.observer.observe(this.root); }
  }
  call(method: string, argument?: unknown): Promise<unknown> { if (this.destroyed) return Promise.reject(new Error('StructureViewport has been destroyed.'));
    return this.ready.then((viewer) => { const action = viewer[method]; if (typeof action !== 'function') throw new Error(`The molecular viewer does not support ${method}.`); return action.call(viewer, argument); }); }
  loadStructure(value: unknown): Promise<unknown> { return this.call('loadStructure', value); }
  setRepresentation(value: unknown): Promise<unknown> { return this.call('setRepresentation', value); }
  setColor(value: unknown): Promise<unknown> { return this.call('setColor', value); }
  select(value: unknown): Promise<unknown> { return this.call('select', value); }
  focus(value: unknown): Promise<unknown> { return this.call('focus', value); }
  setTheme(value: unknown): Promise<unknown> { return this.call('setTheme', value); }
  clear(): Promise<unknown> { return this.call('clear'); }
  resetCamera(): Promise<unknown> { return this.call('resetCamera'); }
  captureImage(): Promise<unknown> { return this.call('captureImage'); }
  destroy(): void { if (this.destroyed) return; this.destroyed = true; this.observer?.disconnect(); void this.ready.then((viewer) => viewer.dispose?.()); this.host.replaceChildren(); }
}

export class LocalConfidenceSeries {
  private observer: ResizeObserver | null = null;
  constructor(private readonly host: HTMLElement, private options: Record<string, any>) {
    this.render(); if (typeof ResizeObserver !== 'undefined') { this.observer = new ResizeObserver(() => this.render()); this.observer.observe(host); }
  }
  update(options: Record<string, any>): void { this.options = { ...this.options, ...options }; this.render(); }
  private render(): void {
    const series = this.options.series || []; const length = Math.max(0, ...series.map((item: any) => item.values?.length || 0));
    const xValues = this.options.xValues || Array.from({ length }, (_, index) => index + 1);
    const all = series.flatMap((item: any) => item.values || []).map(Number).filter(Number.isFinite);
    if (!all.length || all.length > (this.options.maxPoints || 100_000)) throw new Error('The metric series contains no valid bounded data.');
    const width = Math.max(1, Math.min(760, this.host.clientWidth || 760)), height = Math.max(180, Math.round(width * 0.47)), pad = Math.min(44, width * 0.14);
    const yMin = this.options.yMin ?? Math.min(...all); const inferredMax = Math.max(...all);
    const yMax = this.options.yMax ?? (inferredMax === yMin ? yMin + 1 : inferredMax);
    const xs = xValues.map(Number), xMin = Math.min(...xs), xMax = Math.max(...xs);
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.style.display = 'block'; svg.style.width = '100%'; svg.style.height = 'auto';
    svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', `${this.options.yLabel || 'Metric'} by ${this.options.xLabel || 'index'}`);
    series.forEach((item: any, seriesIndex: number) => { let drawing = false; const commands = item.values.map((raw: unknown, index: number) => {
      const value = Number(raw), xValue = xs[index]; if (!Number.isFinite(value) || !Number.isFinite(xValue)) { drawing = false; return ''; }
      const x = pad + (width - 2 * pad) * (xValue! - xMin) / Math.max(xMax - xMin, 1);
      const y = height - pad - (height - 2 * pad) * (value - yMin) / Math.max(yMax - yMin, 1e-9);
      const command = drawing ? 'L' : 'M'; drawing = true; return `${command}${x.toFixed(1)} ${y.toFixed(1)}`;
    }).filter(Boolean).join(' '); const path = document.createElementNS(svg.namespaceURI, 'path');
      path.setAttribute('d', commands); path.setAttribute('fill', 'none'); path.setAttribute('stroke', item.color || ['#087f8c', '#c44536', '#6a4c93'][seriesIndex % 3]!); path.setAttribute('stroke-width', '2'); svg.append(path);
    }); this.host.replaceChildren(svg);
  }
  destroy(): void { this.observer?.disconnect(); this.host.replaceChildren(); }
}

export class PairMatrix {
  private values: Array<Array<number | null>> = [];
  private xLabels: string[] = [];
  private yLabels: string[] = [];
  private xGroups: unknown[] = [];
  private yGroups: unknown[] = [];
  private selected = { x: 0, y: 0 };
  private showBorders = false;
  private readonly maximumElements: number;
  private observer: ResizeObserver | null = null;
  private themeObserver: MutationObserver | null = null;
  private readonly click = (event: MouseEvent): void => this.pick(event, true);
  private readonly pointer = (event: PointerEvent): void => this.pick(event, false);
  private readonly keydown = (event: KeyboardEvent): void => {
    const moves: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const move = moves[event.key]; if (!move || !this.ready()) return; event.preventDefault(); this.select(this.selected.x + move[0], this.selected.y + move[1]);
  };
  constructor(private readonly options: Record<string, any>) {
    if (!options.figure || !options.canvas) throw new TypeError('PairMatrix requires figure and canvas elements.');
    this.maximumElements = options.maxElements ?? MAX_ELEMENTS;
    if (!Number.isInteger(this.maximumElements) || this.maximumElements < 1 || this.maximumElements > MAX_ELEMENTS) throw new RangeError('PairMatrix element limit is invalid.');
    options.canvas.addEventListener('click', this.click); options.canvas.addEventListener('pointermove', this.pointer); options.canvas.addEventListener('keydown', this.keydown);
    const observed = options.observe || options.figure.parentElement;
    if (typeof ResizeObserver !== 'undefined' && observed) { this.observer = new ResizeObserver(() => this.draw()); this.observer.observe(observed); }
    if (typeof MutationObserver !== 'undefined') { this.themeObserver = new MutationObserver(() => this.draw()); this.themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] }); }
  }
  setData(data: { values: Array<Array<number | null>>; xLabels?: string[]; yLabels?: string[]; xGroups?: unknown[]; yGroups?: unknown[] }): void {
    if (!data.values.length || !data.values[0]?.length || data.values.length * data.values[0].length > this.maximumElements) throw new RangeError('The pair matrix exceeds the element limit.');
    const columns = data.values[0]!.length;
    if (data.values.some((row) => row.length !== columns)) throw new TypeError('PairMatrix rows must have equal length.');
    this.values = data.values; this.xLabels = [...(data.xLabels || [])].map(String); this.yLabels = [...(data.yLabels || [])].map(String);
    this.xGroups = [...(data.xGroups || [])]; this.yGroups = [...(data.yGroups || data.xGroups || [])];
    while (this.xLabels.length < columns) this.xLabels.push(String(this.xLabels.length + 1));
    while (this.yLabels.length < data.values.length) this.yLabels.push(String(this.yLabels.length + 1));
    this.selected = { x: 0, y: 0 }; this.draw();
  }
  setBorders(shown: boolean): void { this.showBorders = shown; this.draw(); }
  private ready(): boolean { return Boolean(this.values.length && this.values[0]?.length); }
  private clamp(x: number, y: number): { x: number; y: number } { return { x: Math.max(0, Math.min(this.values[0]!.length - 1, x)), y: Math.max(0, Math.min(this.values.length - 1, y)) }; }
  private geometry(): { width: number; height: number; left: number; top: number; size: number; legendX: number; legendWidth: number; scale: number } {
    const base = this.options.geometry || { width: 800, height: 600, left: 78, top: 30, size: 500, legendX: 604, legendWidth: 24 };
    const available = (this.options.observe || this.options.figure.parentElement)?.clientWidth || base.width;
    const width = Math.max(1, Math.min(base.width, available)), scale = width / base.width;
    return { width, height: Math.round(base.height * scale), left: base.left * scale, top: base.top * scale, size: base.size * scale, legendX: base.legendX * scale, legendWidth: Math.max(8, base.legendWidth * scale), scale };
  }
  private cellFromEvent(event: MouseEvent | PointerEvent): { x: number; y: number } | null {
    const canvas = this.options.canvas as HTMLCanvasElement, box = canvas.getBoundingClientRect(), geometry = this.geometry();
    const localX = (event.clientX - box.left) * geometry.width / box.width, localY = (event.clientY - box.top) * geometry.height / box.height;
    if (localX < geometry.left || localX >= geometry.left + geometry.size || localY < geometry.top || localY >= geometry.top + geometry.size) return null;
    return this.clamp(Math.floor((localX - geometry.left) / geometry.size * this.values[0]!.length), Math.floor((localY - geometry.top) / geometry.size * this.values.length));
  }
  private cell(x: number, y: number): Record<string, any> { const raw = this.values[y]?.[x]; return { x, y, value: raw == null ? Number.NaN : Number(raw), xLabel: this.xLabels[x], yLabel: this.yLabels[y], xGroup: this.xGroups[x], yGroup: this.yGroups[y] }; }
  private pick(event: MouseEvent | PointerEvent, selected: boolean): void { if (!this.ready()) return; const cell = this.cellFromEvent(event); if (!cell) return;
    if (selected) this.select(cell.x, cell.y); else { this.report(cell.x, cell.y); this.options.onHover?.(this.cell(cell.x, cell.y)); }
  }
  private select(x: number, y: number): void { this.selected = this.clamp(x, y); this.draw(); this.options.onSelect?.(this.cell(this.selected.x, this.selected.y)); }
  private report(x: number, y: number): void { if (!this.options.readout) return; const cell = this.cell(x, y);
    const value = Number.isFinite(cell.value) ? cell.value.toFixed(this.options.decimals ?? 1) : 'N/A';
    this.options.readout.textContent = this.options.formatReadout?.(cell) || `${this.options.xTitle || 'Column'} ${cell.xLabel} · ${this.options.yTitle || 'Row'} ${cell.yLabel} · value ${value}${this.options.unit ? ` ${this.options.unit}` : ''}`;
  }
  private draw(): void {
    if (!this.ready()) return; const canvas = this.options.canvas as HTMLCanvasElement, figure = this.options.figure as HTMLElement;
    const geometry = this.geometry(), dpr = window.devicePixelRatio || 1, context = canvas.getContext('2d'); if (!context) return;
    canvas.width = Math.round(geometry.width * dpr); canvas.height = Math.round(geometry.height * dpr); canvas.style.width = `${geometry.width}px`; canvas.style.height = `${geometry.height}px`;
    figure.style.width = `${geometry.width}px`; figure.style.height = `${geometry.height}px`; context.setTransform(dpr, 0, 0, dpr, 0, 0); context.clearRect(0, 0, geometry.width, geometry.height);
    const numeric = this.values.flat().map(Number).filter(Number.isFinite), minimum = this.options.minimum ?? (numeric.length ? Math.min(...numeric) : 0), maximum = this.options.maximum ?? (numeric.length ? Math.max(...numeric) : 1), span = maximum - minimum || 1;
    const configuredRamp = typeof this.options.ramp === 'function' ? this.options.ramp() : this.options.ramp;
    const ramp: string[] = configuredRamp || ['#eef7fb', '#7db9dc', '#155b8a']; if (!Array.isArray(ramp) || ramp.length < 2) throw new Error('PairMatrix requires at least two colours.');
    const cells = document.createElement('canvas'); cells.width = this.values[0]!.length; cells.height = this.values.length;
    const cellContext = cells.getContext('2d'); if (!cellContext) return; const image = cellContext.createImageData(cells.width, cells.height);
    const color = (value: number): [number, number, number] => { if (!Number.isFinite(value)) return [119, 119, 119]; const ratio = Math.max(0, Math.min(1, (value - minimum) / span)); const index = Math.min(ramp.length - 2, Math.floor(ratio * (ramp.length - 1))), blend = ratio * (ramp.length - 1) - index;
      const first = ramp[index]!, second = ramp[index + 1]!;
      return [1, 3, 5].map((offset) => Math.round(parseInt(first.slice(offset, offset + 2), 16) + (parseInt(second.slice(offset, offset + 2), 16) - parseInt(first.slice(offset, offset + 2), 16)) * blend)) as [number, number, number]; };
    this.values.forEach((row, y) => row.forEach((raw, x) => { const rgb = color(raw == null ? Number.NaN : Number(raw)), offset = (y * cells.width + x) * 4; image.data.set([...rgb, 255], offset); }));
    cellContext.putImageData(image, 0, 0); context.imageSmoothingEnabled = false; context.drawImage(cells, geometry.left, geometry.top, geometry.size, geometry.size);
    const ink = getComputedStyle(document.body).getPropertyValue('--ink').trim() || '#1d2a2f'; context.strokeStyle = ink; context.strokeRect(geometry.left, geometry.top, geometry.size, geometry.size);
    if (this.showBorders) [this.xGroups, this.yGroups].forEach((groups, axis) => { for (let index = 1; index < groups.length; index += 1) { if (groups[index] === groups[index - 1]) continue; const offset = geometry.size * index / groups.length; context.beginPath(); axis ? (context.moveTo(geometry.left, geometry.top + offset), context.lineTo(geometry.left + geometry.size, geometry.top + offset)) : (context.moveTo(geometry.left + offset, geometry.top), context.lineTo(geometry.left + offset, geometry.top + geometry.size)); context.stroke(); } });
    const gradient = context.createLinearGradient(0, geometry.top, 0, geometry.top + geometry.size); ramp.forEach((entry: string, index: number) => gradient.addColorStop(1 - index / (ramp.length - 1), entry)); context.fillStyle = gradient; context.fillRect(geometry.legendX, geometry.top, geometry.legendWidth, geometry.size);
    const selectedX = geometry.left + geometry.size * (this.selected.x + 0.5) / this.values[0]!.length, selectedY = geometry.top + geometry.size * (this.selected.y + 0.5) / this.values.length;
    context.lineWidth = 3; context.strokeStyle = '#fff'; context.strokeRect(selectedX - 6, selectedY - 6, 12, 12); context.lineWidth = 1; context.strokeStyle = ink; context.strokeRect(selectedX - 6, selectedY - 6, 12, 12);
    this.drawLabels(geometry, minimum, maximum); this.report(this.selected.x, this.selected.y); this.options.onDraw?.({ rows: this.values.length, columns: this.values[0]!.length, minimum, maximum, geometry });
  }
  private drawLabels(geometry: ReturnType<PairMatrix['geometry']>, minimum: number, maximum: number): void {
    const figure = this.options.figure as HTMLElement; figure.querySelectorAll('.pair-matrix-label').forEach((node) => node.remove()); const ticks = Math.max(1, this.options.ticks ?? 5), span = maximum - minimum || 1;
    const label = (text: string, styles: Partial<CSSStyleDeclaration>, classes = ''): void => { const node = document.createElement('span'); node.className = `pair-matrix-label ${classes}`; node.textContent = text; Object.assign(node.style, styles); figure.append(node); };
    for (let tick = 0; tick <= ticks; tick += 1) { const x = Math.round((this.values[0]!.length - 1) * tick / ticks), y = Math.round((this.values.length - 1) * tick / ticks);
      label(this.xLabels[x]!, { left: `${geometry.left + geometry.size * (x + 0.5) / this.values[0]!.length}px`, top: `${geometry.top + geometry.size + 8 * geometry.scale}px` }, 'pair-matrix-label-x');
      label(this.yLabels[y]!, { left: '0', width: `${geometry.left - 8 * geometry.scale}px`, textAlign: 'right', top: `${geometry.top + geometry.size * (y + 0.5) / this.values.length}px` }, 'pair-matrix-label-y');
      label((minimum + span * tick / ticks).toFixed(this.options.decimals ?? 1), { left: `${geometry.legendX + geometry.legendWidth + 7 * geometry.scale}px`, top: `${geometry.top + geometry.size - geometry.size * tick / ticks}px` }, 'pair-matrix-label-y');
    }
    label(this.options.xTitle || 'Column', { left: `${geometry.left + geometry.size / 2}px`, top: `${geometry.top + geometry.size + 26 * geometry.scale}px` }, 'pair-matrix-title pair-matrix-label-x');
    label(this.options.yTitle || 'Row', { left: `${20 * geometry.scale}px`, top: `${geometry.top + geometry.size / 2}px` }, 'pair-matrix-title pair-matrix-title-y');
    label(this.options.legendTitle || 'Scale', { left: `${geometry.legendX}px`, top: `${geometry.top - 18 * geometry.scale}px` }, 'pair-matrix-title');
  }
  destroy(): void { this.observer?.disconnect(); this.themeObserver?.disconnect(); const canvas = this.options.canvas as HTMLCanvasElement;
    canvas.removeEventListener('click', this.click); canvas.removeEventListener('pointermove', this.pointer); canvas.removeEventListener('keydown', this.keydown); (this.options.figure as HTMLElement).querySelectorAll('.pair-matrix-label').forEach((node) => node.remove()); }
}

export class AlignmentCoverage {
  readonly rowCount: number;
  constructor(private readonly host: HTMLElement, text: string, options: { maxRows?: number; title?: string } = {}) {
    const sequences: Array<{ name: string; sequence: string }> = []; let current: { name: string; sequence: string } | null = null;
    String(text || '').split(/\r?\n/).forEach((line) => { if (line.startsWith('>')) { current = sequences.length >= (options.maxRows || 5000) ? null : { name: line.slice(1).trim(), sequence: '' }; if (current) sequences.push(current); } else if (current) current.sequence += line.trim(); });
    const pre = document.createElement('pre'); pre.className = 'msa-block'; pre.setAttribute('role', 'img'); pre.setAttribute('aria-label', options.title || 'Alignment coverage');
    sequences.forEach((item) => { const heading = document.createElement('span'); heading.className = 'msa-header'; heading.textContent = `>${item.name}`; const sequence = document.createElement('span'); sequence.className = 'msa-sequence'; sequence.textContent = item.sequence; pre.append(heading, sequence); });
    host.replaceChildren(pre); this.rowCount = sequences.length;
  }
  destroy(): void { this.host.replaceChildren(); }
}
export class EntitySummaryTable {
  constructor(private readonly host: HTMLElement, private options: { columns?: string[]; rows?: unknown[][]; store?: ResultSelectionStore; selection?: (row: unknown[], index: number) => Partial<SelectionState>; onSelect?: (row: unknown[], index: number) => void }) { this.render(); }
  private render(): void { const table = document.createElement('table'); table.className = 'artifact-table-preview entity-result-table'; const heading = document.createElement('tr');
    (this.options.columns || []).forEach((column) => { const th = document.createElement('th'); th.scope = 'col'; th.textContent = column; heading.append(th); }); table.append(heading);
    (this.options.rows || []).forEach((row, index) => { const tr = document.createElement('tr'); tr.tabIndex = 0; tr.setAttribute('aria-selected', 'false'); row.forEach((value) => { const td = document.createElement('td'); td.textContent = String(value ?? ''); tr.append(td); });
      const select = (): void => { table.querySelectorAll('[aria-selected="true"]').forEach((node) => node.setAttribute('aria-selected', 'false')); tr.setAttribute('aria-selected', 'true'); this.options.store?.set(this.options.selection?.(row, index) || { entityA: String(row[0] ?? '') }, table); this.options.onSelect?.(row, index); };
      tr.addEventListener('click', select); tr.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); } }); table.append(tr); }); this.host.replaceChildren(table); }
  update(options: Partial<EntitySummaryTable['options']>): void { this.options = { ...this.options, ...options }; this.render(); }
  destroy(): void { this.host.replaceChildren(); }
}

export const scientificPrimitives = Object.freeze({
  ResultSelectionStore, CandidateSelector, ScalarMetricGrid, LocalConfidenceSeries, PairMatrix,
  StructureViewport, AlignmentCoverage, EntitySummaryTable, loadProjection, loadNumericProjection,
});

declare global { interface Window { REvoComputeScientific?: typeof scientificPrimitives } }
export function installScientificPrimitives(): void { window.REvoComputeScientific = scientificPrimitives; }
