import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createScalarSummaryViewRenderer,
  declaredFields,
  resolveScalarPath,
  scalarMetrics,
} from '../src/features/results/scalar-summary-view';
import { HarnessNode, installHarness } from './dom-harness';

const FIELDS = [
  { path: 'ptm', label: 'pTM', unit: 'score', direction: 'higher' },
  { path: 'iptm', label: 'ipTM', unit: 'score', direction: 'higher', nullable: true },
  { path: 'has_clash', label: 'Has clash', unit: 'flag', direction: 'lower' },
];
const VIEW = {
  id: 'confidence_summary', plugin: 'scalar-summary', role: 'evidence', title: 'Structure confidence',
  description: 'Global confidence measures.', sources: { data: ['summary.json'] }, mapping: { fields: FIELDS },
};
const ARTIFACT = {
  path: 'summary.json', size: 100, sha256: 'a'.repeat(64), url: '/artifacts/summary.json',
  media_type: 'application/json', preview: 'text', capability: 'text', role: 'evidence',
};

function serve(body: unknown, status = 200): void {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

function gridText(host: HarnessNode): string {
  return host.querySelector('.scalar-grid')?.textContent ?? '';
}

beforeEach(() => installHarness(vi.stubGlobal));
afterEach(() => vi.unstubAllGlobals());

describe('resolveScalarPath', () => {
  it('follows dotted object keys and decimal array indices like the server', () => {
    expect(resolveScalarPath({ a: { b: [10, 20] } }, 'a.b.1')).toBe(20);
    expect(resolveScalarPath({ a: 0 }, 'a')).toBe(0);
    expect(resolveScalarPath({ a: { b: 1 } }, 'a.missing')).toBeUndefined();
  });
});

describe('scalarMetrics', () => {
  it('renders the declared values on their published scale with direction wording', () => {
    expect(scalarMetrics({ ptm: 0.88, iptm: null, has_clash: 0 }, FIELDS)).toEqual([
      { label: 'pTM', value: 0.88, unit: 'score', meaning: 'Higher is better' },
      { label: 'ipTM', value: null, unit: 'score', meaning: 'Higher is better', nullable: true },
      { label: 'Has clash', value: 0, unit: 'flag', meaning: 'Lower is better' },
    ]);
  });

  it('fails a declared non-nullable field that is absent or not a scalar', () => {
    expect(() => scalarMetrics({ iptm: null }, FIELDS)).toThrow('no scalar value at the declared path ptm');
    expect(() => scalarMetrics({ ptm: [0.5], iptm: null, has_clash: 0 }, FIELDS)).toThrow('ptm');
    expect(() => scalarMetrics([1, 2], FIELDS)).toThrow('not a JSON object');
  });
});

describe('declaredFields', () => {
  it('accepts the server-projected declaration and refuses a malformed one', () => {
    expect(declaredFields(VIEW as never)).toHaveLength(3);
    expect(() => declaredFields({ ...VIEW, mapping: {} } as never)).toThrow('cannot render');
    expect(() => declaredFields({ ...VIEW, mapping: { fields: [{ ...FIELDS[0], direction: 'up' }] } } as never))
      .toThrow('cannot render');
  });
});

describe('scalar-summary view renderer', () => {
  it('renders the first declared source through the shared scalar grid without rescaling', async () => {
    serve({ ptm: 0.88, iptm: null, has_clash: 0 });
    const host = new HarnessNode('div');
    const handle = await createScalarSummaryViewRenderer().render(
      VIEW as never, { data: [ARTIFACT] } as never, host as unknown as HTMLElement,
      { signal: new AbortController().signal, taskId: 'a'.repeat(32) },
    );
    expect(host.querySelector('section.scalar-summary-view')).not.toBeNull();
    expect(gridText(host)).toContain('pTM0.88 score');
    expect(gridText(host)).toContain('ipTMN/AHigher is better');
    expect(gridText(host)).toContain('Has clash0 flag');
    expect(host.querySelector('p.result-note')?.textContent).toContain('exactly as the runner published them');
    expect(fetch).toHaveBeenCalledWith('/artifacts/summary.json', expect.objectContaining({ credentials: 'same-origin' }));
    expect((handle as { destroy(): void }).destroy).toBeTypeOf('function');
  });

  it('states the missing source, a failed read, and an unresolvable declared field', async () => {
    const host = new HarnessNode('div');
    const context = { signal: new AbortController().signal, taskId: 'a'.repeat(32) };
    await expect(createScalarSummaryViewRenderer().render(VIEW as never, { data: [] } as never, host as unknown as HTMLElement, context))
      .rejects.toThrow('no published data source');
    serve({}, 500);
    await expect(createScalarSummaryViewRenderer().render(VIEW as never, { data: [ARTIFACT] } as never, host as unknown as HTMLElement, context))
      .rejects.toThrow('could not be loaded');
    serve({ iptm: null, has_clash: false });
    await expect(createScalarSummaryViewRenderer().render(VIEW as never, { data: [ARTIFACT] } as never, host as unknown as HTMLElement, context))
      .rejects.toThrow('ptm');
  });
});
