import { afterEach, describe, expect, it, vi } from 'vitest';

import { HarnessNode, harnessDocument, installHarness } from './dom-harness';

/*
 * A reconstructed draft must never accept an incompatible scientific setting
 * by default. The plan reports each blocked recorded value; the form keeps the
 * current default only as a starting point, refuses to run until the reader
 * resolves it, and stops claiming a value came from the source once it is
 * edited or the clone is cleared.
 */

const ENVIRONMENT_URL = '/compute/api/environment';
const CATALOG_URL = '/compute/api/types';
const DETAIL_URL = '/compute/api/types/method';
const PARAMETERS_URL = '/compute/api/task-parameters/method';
const PLAN_ID = 'plan_reference_reference';
const PLAN_URL = `/compute/api/clone-plans/${PLAN_ID}`;
const PREFLIGHT_URL = '/compute/api/preflight/method';
const SOURCE_ID = 'a'.repeat(32);

const CATALOG = {
  categories: [{ name: 'evolution', label: 'Evolution' }],
  task_types: [{ name: 'method', display_name: 'Method', summary: 'A method', category: 'evolution', access: { restricted: false } }],
};

const DETAIL = {
  name: 'method', display_name: 'Method', category: 'evolution', summary: 'A method',
  use_when: 'Always', input_summary: 'No inputs', output_summary: 'A summary', gpus: false,
  access: { restricted: false }, parameters_url: PARAMETERS_URL, inputs: [],
  input_workspace: {
    version: 3, plugins: [], steps: [{
      id: 'settings', title: 'Settings',
      capabilities: [{ plugin: 'parameters', id: 'parameters', title: 'Parameters', options: {} }],
    }],
  },
  max_request_bytes: 1_000_000,
};

const PARAMETERS = {
  type: 'object',
  properties: {
    seed: { type: 'integer', title: 'Seed', default: 7 },
    mode: { type: 'string', title: 'Mode', default: 'exact' },
    temperature: { type: 'number', title: 'Temperature', default: 0.5 },
  },
};

const PLAN = {
  plan_id: PLAN_ID,
  expires_at: null,
  source_task_id: SOURCE_ID,
  source_task_type: 'method',
  source_submitted_at: null,
  target_task_type: 'method',
  target_display_name: 'Method',
  target_schema_revision: null,
  compatible_parameters: [{ name: 'seed', value: '5', source: 'recorded' }],
  reusable_inputs: [],
  warnings: [],
  blocked_fields: [
    { field: 'mode', code: 'parameter_choice_unavailable', message: 'The recorded choice is no longer accepted.', recorded_value: 'fast' },
    { field: 'temperature', code: 'parameter_range_invalid', message: 'The recorded value is above the current maximum.', recorded_value: '9.5' },
  ],
  can_submit: false,
};

type Modules = {
  CreateTask: typeof import('../src/features/create-task/CreateTask').CreateTask;
  harness: typeof import('./dom-harness');
};

function reply(payload: unknown): Response {
  return { ok: true, status: 200, json: async () => payload } as unknown as Response;
}

class HarnessOption extends HarnessNode {
  constructor(text: string, value: string) {
    super('option');
    this.textContent = text;
    this.setAttribute('value', value);
  }
}

async function load(options: { clone?: boolean } = {}): Promise<Modules> {
  vi.resetModules();
  installHarness(vi.stubGlobal, { pathname: '/compute/create_task' });
  vi.stubGlobal('Option', HarnessOption);
  // Form controls are harness nodes, so the element classes they are tested
  // against cannot match; the branches that need a real select's options are
  // exercised by the browser suite, not here.
  vi.stubGlobal('HTMLInputElement', class {});
  vi.stubGlobal('HTMLSelectElement', class {});
  vi.stubGlobal('CSS', { escape: (value: string) => value });
  const documentStub = harnessDocument as unknown as { createElement: (tag: string) => HarnessNode };
  const createElement = documentStub.createElement.bind(documentStub);
  documentStub.createElement = (tag: string) => Object.assign(createElement(tag), { value: '' });
  const browser = (globalThis as unknown as {
    window: { location: Record<string, unknown>; scrollTo: () => void };
  }).window;
  browser.location.search = options.clone === false ? '' : `?clone=${PLAN_ID}`;
  browser.location.href = `https://revocompute.invalid/compute/create_task${browser.location.search}`;
  browser.scrollTo = () => {};
  vi.stubGlobal('history', { replaceState: () => {} });
  return {
    CreateTask: (await import('../src/features/create-task/CreateTask')).CreateTask,
    harness: await import('./dom-harness'),
  };
}

async function mount(CreateTask: Modules['CreateTask'], preflights: FormData[]): Promise<HarnessNode> {
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    if (url === ENVIRONMENT_URL) return reply({ version: 1, demo_mode: false, execution: 'available' });
    if (url === CATALOG_URL) return reply(CATALOG);
    if (url === DETAIL_URL) return reply(DETAIL);
    if (url === PARAMETERS_URL) return reply(PARAMETERS);
    if (url === PLAN_URL) return reply(PLAN);
    if (url === '/compute/api/auth/token') return reply({ token: 'test-token' });
    if (url === PREFLIGHT_URL) {
      preflights.push(init!.body as FormData);
      // Stop at a validation refusal: the body is what this test reads, and no
      // Task is created.
      return reply({ valid: false, errors: [{ code: 'test_refusal', message: 'Not submitted.', blocking: true }], warnings: [], admission: { runner_ready: true, infrastructure_status: 'READY', infrastructure_ready: true } });
    }
    throw new Error(`unexpected request ${url}`);
  }));
  const root = document.createElement('div') as unknown as HarnessNode;
  harnessDocument.body.append(root);
  await new CreateTask(root as unknown as HTMLElement).mount();
  return root;
}

const action = (root: HarnessNode): HarnessNode => root.querySelector('.ct-snapshot-panel .ct-actions button.ct-primary')!;
const clear = (root: HarnessNode): HarnessNode => root.querySelector('.ct-snapshot-panel .ct-actions button.ct-secondary')!;

afterEach(() => vi.unstubAllGlobals());

describe('a cloned draft with blocked settings', () => {
  it('shows the recorded values and refuses to run until each is resolved', async () => {
    const { CreateTask } = await load();
    const root = await mount(CreateTask, []);
    const conflicts = root.querySelector('.ct-clone-conflicts')!;
    expect(conflicts.textContent).toContain('fast');
    expect(conflicts.textContent).toContain('9.5');
    expect(root.querySelector('.ct-validation')!.textContent).toContain('Resolve the blocked setting');
    expect(action(root).disabled).toBe(true);

    // Resolving one conflict leaves the other one required.
    root.querySelectorAll('.ct-clone-conflicts button')[0]!.dispatch('click', {});
    expect(root.querySelectorAll('.ct-clone-conflicts li')).toHaveLength(1);
    expect(action(root).disabled).toBe(true);

    root.querySelectorAll('.ct-clone-conflicts button')[0]!.dispatch('click', {});
    expect(root.querySelector('.ct-clone-conflicts')).toBeNull();
    expect(action(root).disabled).toBe(false);
  });

  it('records the source only while the clone owns the draft, and only edited fields lose their source label', async () => {
    const { CreateTask } = await load();
    const preflights: FormData[] = [];
    const root = await mount(CreateTask, preflights);

    // An edit to a compatible recorded value is no longer the source's value.
    const seed = root.querySelector('[data-ct-parameter="seed"]')!;
    (seed as unknown as { value: string }).value = '9';
    seed.dispatch('input', {});
    const seedRow = root.querySelectorAll('.ct-clone-parameters li').find(row => row.textContent.includes('seed'))!;
    expect(seedRow.textContent).toContain('Edited in this draft');
    expect(seedRow.textContent).not.toContain('From the source task');
    expect(seedRow.textContent).toContain('9');

    while (root.querySelectorAll('.ct-clone-conflicts button').length) {
      root.querySelectorAll('.ct-clone-conflicts button')[0]!.dispatch('click', {});
    }
    action(root).dispatch('click', {});
    await vi.waitFor(() => expect(preflights).toHaveLength(1));
    expect(preflights[0]!.get('cloned_from')).toBe(SOURCE_ID);

    // Clearing the workspace discards the cloned values and their lineage.
    clear(root).dispatch('click', {});
    await vi.waitFor(() => expect(root.querySelector('.ct-clone')).toBeNull());
    expect(root.querySelectorAll('.ct-clone-conflicts')).toHaveLength(0);
    // Clear remounts the workspace asynchronously; run only the settled form.
    await vi.waitFor(() => expect(root.querySelector('.ct-status')!.textContent).toContain('Workspace cleared.'));

    action(root).dispatch('click', {});
    await vi.waitFor(() => expect(preflights).toHaveLength(2));
    expect(preflights[1]!.get('cloned_from')).toBeNull();
  });
});
