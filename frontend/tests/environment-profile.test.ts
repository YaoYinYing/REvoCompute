import { afterEach, describe, expect, it, vi } from 'vitest';

import { HarnessNode, installHarness } from './dom-harness';

/*
 * The deployment profile is a Server fact, and it is a label rather than the
 * submission boundary.
 *
 * An unanswered read stays distinguishable from production so the form can say
 * it is unresolved and offer a retry. It must not gate execution: production
 * availability cannot depend on a cosmetic endpoint, and a demo deployment that
 * cannot answer its own profile still refuses at the Server. The run control
 * waits only while the read is genuinely in flight, so a demo deployment never
 * flashes an executable control.
 */

const ENVIRONMENT_URL = '/compute/api/environment';
const TASK_DETAIL_URL = '/compute/api/types/sequence_demo';
const PARAMETERS_URL = '/compute/api/task-parameters/sequence_demo';
const DEMO_ENVIRONMENT = { version: 1, demo_mode: true, execution: 'preview_only', notice: 'Demo environment: preview and replay only.' };

const CATALOG = {
  categories: [{ name: 'evolution', label: 'Evolution' }],
  task_types: [{ name: 'sequence_demo', display_name: 'Sequence demo', summary: 'A demo task', category: 'evolution', access: { restricted: false } }],
};

const DETAIL = {
  name: 'sequence_demo', display_name: 'Sequence demo', category: 'evolution', summary: 'A demo task',
  use_when: 'Always', input_summary: 'No inputs', output_summary: 'A summary', gpus: false,
  access: { restricted: false }, parameters_url: PARAMETERS_URL, inputs: [],
  input_workspace: { version: 3, plugins: [], steps: [] }, max_request_bytes: 1_000_000,
};

type Modules = {
  CreateTask: typeof import('../src/features/create-task/CreateTask').CreateTask;
  environment: typeof import('../src/app/environment');
};

function reply(payload: unknown): Response {
  return { ok: true, status: 200, json: async () => payload } as unknown as Response;
}

/** The catalog builds `<option>` elements; they must be harness nodes to append. */
class HarnessOption extends HarnessNode {
  constructor(text: string, value: string) {
    super('option');
    this.textContent = text;
    this.setAttribute('value', value);
  }
}

/** Load fresh modules over the harness, opening the Create Task form for one task. */
async function load(): Promise<Modules> {
  vi.resetModules();
  installHarness(vi.stubGlobal, { pathname: '/compute/create_task' });
  vi.stubGlobal('Option', HarnessOption);
  // The catalog reads `input.value`; harness nodes model the element surface the
  // component touches, so give form controls the empty initial value a browser does.
  const documentStub = (globalThis as unknown as { document: { createElement: (tag: string) => HarnessNode } }).document;
  const createElement = documentStub.createElement.bind(documentStub);
  documentStub.createElement = (tag: string) => Object.assign(createElement(tag), { value: '' });
  const browser = (globalThis as unknown as {
    window: { location: Record<string, unknown>; scrollTo: () => void };
  }).window;
  browser.location.search = '?task_type=sequence_demo';
  browser.location.href = 'https://revocompute.invalid/compute/create_task?task_type=sequence_demo';
  browser.scrollTo = () => {};
  vi.stubGlobal('history', { replaceState: () => {} });
  return {
    CreateTask: (await import('../src/features/create-task/CreateTask')).CreateTask,
    environment: await import('../src/app/environment'),
  };
}

/** Serve the catalog and task contract, and whatever the profile endpoint answers. */
function routeFetch(profile: () => Promise<Response> | Response): void {
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = String(input);
    if (url === ENVIRONMENT_URL) return profile();
    if (url === '/compute/api/types') return reply(CATALOG);
    if (url === TASK_DETAIL_URL) return reply(DETAIL);
    if (url === PARAMETERS_URL) return reply({ type: 'object', properties: {} });
    throw new Error(`unexpected request ${url}`);
  }));
}

async function mount(CreateTask: Modules['CreateTask']): Promise<HarnessNode> {
  const root = document.createElement('div') as unknown as HarnessNode;
  await new CreateTask(root as unknown as HTMLElement).mount();
  return root;
}

const action = (root: HarnessNode): HarnessNode => root.querySelector('.ct-actions button.ct-primary')!;

/** Whether the element and every ancestor it is rendered under are visible. */
function visible(node: HarnessNode): boolean {
  for (let current: HarnessNode | null = node; current; current = current.parent) {
    if (current.hidden) return false;
  }
  return true;
}

afterEach(() => vi.unstubAllGlobals());

describe('the deployment profile read', () => {
  it('leaves a failed read unresolved instead of substituting production', async () => {
    const { environment } = await load();
    routeFetch(() => Promise.reject(new TypeError('network down')));
    // Unresolved is a distinct fact: the form states it. It is not a production answer.
    await expect(environment.loadEnvironment()).resolves.toBeNull();
  });

  it('leaves an error response unresolved', async () => {
    const { environment } = await load();
    routeFetch(() => ({ ok: false, status: 503, json: async () => ({}) }) as unknown as Response);
    await expect(environment.loadEnvironment()).resolves.toBeNull();
  });

  it('rejects a malformed 200 body instead of defaulting it to production', async () => {
    const { environment } = await load();
    const malformed: unknown[] = [
      {},
      { version: 1, demo_mode: true },
      { version: 1, demo_mode: 'true', execution: 'available' },
      { version: 2, demo_mode: true, execution: 'preview_only' },
      { version: 1, demo_mode: true, execution: 'live' },
      [],
    ];
    for (const body of malformed) {
      routeFetch(() => reply(body));
      await expect(environment.loadEnvironment()).resolves.toBeNull();
    }
  });

  it('does not cache the failure, so the retry reads again', async () => {
    const { environment } = await load();
    const profile = vi.fn()
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce(reply(DEMO_ENVIRONMENT));
    routeFetch(profile);
    await expect(environment.loadEnvironment()).resolves.toBeNull();
    await expect(environment.loadEnvironment()).resolves.toMatchObject({ demo_mode: true, execution: 'preview_only' });
    expect(profile).toHaveBeenCalledTimes(2);
  });

  it('reports a resolved production profile unchanged', async () => {
    const { environment } = await load();
    routeFetch(() => reply({ version: 1, demo_mode: false, execution: 'available' }));
    await expect(environment.loadEnvironment()).resolves.toEqual({ version: 1, demo_mode: false, execution: 'available' });
  });
});

describe('the Create Task run control', () => {
  it('stays available and states an unresolved profile, leaving the server as the boundary', async () => {
    const { CreateTask } = await load();
    routeFetch(() => Promise.reject(new TypeError('network down')));
    const root = await mount(CreateTask);
    const notice = root.querySelector('.ct-environment-notice')!;
    expect(notice.hidden).toBe(false);
    expect(notice.textContent).toContain('server still decides');
    expect(notice.querySelector('button')!.textContent).toBe('Retry');
    expect(action(root).disabled).toBe(false);
    // No readiness row is claimed from a profile the browser could not read.
    expect(root.querySelector('.ct-validation-row.info')).toBeNull();
  });

  it('disables the run control on a resolved demo profile', async () => {
    const { CreateTask } = await load();
    routeFetch(() => reply(DEMO_ENVIRONMENT));
    const root = await mount(CreateTask);
    expect(action(root).disabled).toBe(true);
    expect(action(root).textContent).toBe('Preview only — not executable here');
    expect(root.querySelector('.ct-environment-notice')!.hidden).toBe(true);
    // The statement must survive the workbench replacing the page header.
    const notice = root.querySelector('.demo-notice')!;
    expect(notice.closest('.ct-page-header')).toBeNull();
    expect(visible(notice)).toBe(true);
    expect(notice.textContent).toContain('Demo environment');
  });

  it('keeps the ordinary run control and copy on a resolved production profile', async () => {
    const { CreateTask } = await load();
    routeFetch(() => reply({ version: 1, demo_mode: false, execution: 'available' }));
    const root = await mount(CreateTask);
    expect(action(root).disabled).toBe(false);
    expect(root.querySelector('.ct-environment-notice')!.hidden).toBe(true);
    expect(root.querySelectorAll('.demo-notice')).toHaveLength(0);
    expect(root.querySelector('.ct-validation-row.info')!.textContent).toContain('before submission');
  });
});
