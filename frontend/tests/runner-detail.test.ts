import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ParameterDefinition, ParameterSchema, TaskTypeDetail } from '../src/api/app-api';
import { applyLocale } from '../src/app/i18n';
import { mountRunnerDetail } from '../src/features/runners/index';
import { documentOrder, installHarness, type HarnessNode } from './dom-harness';

/*
 * The Runner detail page renders each control's contract as a definition list:
 * a `<dt>` names the fact and the `<dd>` beside it carries the value, so a reader
 * and assistive technology meet a label→value pair. A bounded parameter's range
 * is the same shape. The label is frontend-authored prose and follows the locale
 * while the bound the server projected is emitted verbatim inside it.
 */

const detail = (overrides: Partial<TaskTypeDetail> = {}): TaskTypeDetail => ({
  name: 'sequence_demo', display_name: 'Sequence Demo', category: 'demo',
  summary: 'A synthetic method.', use_when: 'Always applicable.', input_summary: 'No uploads.',
  output_summary: 'A report.', considerations: [], definition_version: 4,
  runtime_family: 'example', gpus: false, requires_network: false, inputs: [], citations: [], workflow: [],
  access: { restricted: false }, detail_url: '/compute/api/types/sequence_demo',
  parameters_url: '/compute/api/task-parameters/sequence_demo', max_request_bytes: 1048576,
  input_workspace: {} as never,
  ...overrides,
});

const schema = (properties: Record<string, ParameterDefinition>): ParameterSchema => ({ properties, required: [] });

beforeEach(() => {
  installHarness(vi.stubGlobal, { pathname: '/runners/sequence_demo' });
});

afterEach(() => { applyLocale('en', false); vi.unstubAllGlobals(); });

/** Mount the real detail page for a Runner whose parameter contract is `contract`. */
async function mountPage(contract: ParameterSchema): Promise<HarnessNode> {
  vi.stubGlobal('fetch', vi.fn(async (url: string | URL) => {
    const payload = String(url).includes('/task-parameters/') ? contract : String(url).endsWith('/infrastructure') ? { status: 'READY' } : detail();
    return new Response(JSON.stringify(payload), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  const root = document.createElement('div') as unknown as HarnessNode;
  await mountRunnerDetail(root as unknown as HTMLElement, 'sequence_demo', { notify: vi.fn(), outlet: root } as never);
  return root;
}

/** Every label→value fact the Controls section publishes for the named parameter. */
function labeledFacts(root: HarnessNode, name: string): Array<[string, string]> {
  const controls = documentOrder(root).find(node => node.id === 'controls');
  expect(controls, 'no Controls section was rendered').toBeDefined();
  const articles = controls!.querySelectorAll('.parameter-list article');
  const article = articles.find(node => node.querySelector('code')?.textContent === name);
  expect(article, `no parameter named ${name}`).toBeDefined();
  return article!.querySelectorAll('dl div').map(row => [row.querySelector('dt')!.textContent, row.querySelector('dd')!.textContent]);
}

describe('Runner detail parameter reference', () => {
  it('keeps exclusive bounds exclusive in the scientific reference', async () => {
    const root = await mountPage(schema({ strength: { type: 'number', exclusiveMinimum: 0, maximum: 10 } }));
    expect(labeledFacts(root, 'strength')).toContainEqual(['Range', '> 0 · ≤ 10']);
  });

  it('names a bounded parameter\'s range as a labelled definition, never a value with an empty label', async () => {
    const root = await mountPage(schema({ msa_depth: { type: 'integer', title: 'MSA depth', description: 'Depth of the search.', minimum: 0, maximum: 100 } }));
    const facts = labeledFacts(root, 'msa_depth');
    // The range is a definition the reader can name: the label and the value
    // occupy their own slots rather than the value inheriting the label styling.
    expect(facts).toContainEqual(['Range', '0 to 100']);
    // Every fact is a label with a value; none is a value beside an empty label.
    expect(facts.filter(([label]) => !label)).toEqual([]);
    expect(facts.every(([, value]) => value.length > 0)).toBe(true);
  });

  it('localizes the range label while the value carries the server-authored bound', async () => {
    applyLocale('zh-CN');
    const root = await mountPage(schema({ msa_depth: { type: 'integer', title: 'MSA depth', description: 'Depth of the search.', minimum: 0, maximum: 100 } }));
    // The label follows the locale; the projected bounds are still what the value
    // states, so a reader in either language sees the same contract.
    expect(labeledFacts(root, 'msa_depth')).toContainEqual(['范围', '0 至 100']);
  });
});
