import { adminApi, type AdminConfiguration, type ExecutionClass, type TaskPlacement, type TaskSummary } from '../api';
import { button, element, empty, formatDate, setBusy, text } from '../shared/dom';

/*
 * The Admin placement register.
 *
 * It answers, for the Tasks the server has already placed, which execution class
 * each one was recorded into — the queue, the accelerator class, and the
 * scheduler fields the decision named — and it answers from the recorded
 * decision the server projects on the Task list, never by resolving today's
 * policy against a historical Task. A Task whose decision was not recorded shows
 * that it was not recorded, with no class invented for it: an absent or
 * unreadable decision is an unknown, and an unknown is not a value.
 *
 * The declared execution-class mapping that produced those decisions is shown
 * exactly as the store spells it. This surface reads policy; it does not edit
 * it, and it never re-spells a value the server has exactly one spelling for.
 */

export type PlacementRecord = 'all' | 'recorded' | 'unrecorded';
export type PlacementState = 'all' | 'cpu' | 'accelerator';
export type PlacementSort = 'submitted' | 'name';

/** Bounded page sizes; a large register is read a page at a time. */
export const PLACEMENT_PAGE_SIZES = [25, 50, 100] as const;
export type PlacementPageSize = (typeof PLACEMENT_PAGE_SIZES)[number];

export interface PlacementQuery {
  query: string;
  state: PlacementState;
  record: PlacementRecord;
  sort: PlacementSort;
}

const STATE_LABEL: Record<ExecutionClass['state'], string> = { cpu: 'CPU', accelerator: 'Accelerator' };

/** The class a Task was recorded into, or the explicit unknown it reports instead. */
export function placementLabel(placement: TaskPlacement): string {
  return placement ? placement.id : 'Not recorded';
}

export function placementStateLabel(placement: ExecutionClass): string {
  return STATE_LABEL[placement.state];
}

/** The deployment-local queue the resolved request named; an unset one is named as unset. */
export function placementQueue(placement: ExecutionClass): string {
  return placement.partition || 'Not named';
}

/** The accelerator the GRES request named: a typed class, an untyped request, or none. */
export function placementDevice(placement: ExecutionClass): string {
  if (placement.state !== 'accelerator') return 'None';
  return placement.device_class ? `${placement.device_class} × ${placement.device_count}` : `Untyped × ${placement.device_count}`;
}

/** Every optional scheduler field reads as unset rather than as an empty cell. */
export function placementSchedulerField(value: string | null): string {
  return value || 'Not set';
}

export function placementExclusive(placement: ExecutionClass): string {
  return placement.exclusive ? 'Exclusive' : 'Not exclusive';
}

/** A recorded runtime, or the explicit unknown when the server has not reported one. */
export function formatWalltime(seconds: number): string {
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return [hours ? `${hours}h` : null, minutes ? `${minutes}m` : null, `${total % 60}s`].filter(Boolean).join(' ');
}

function submittedAt(task: TaskSummary): number {
  const value = task.submitted_at ? Date.parse(task.submitted_at) : Number.NaN;
  return Number.isNaN(value) ? Number.NEGATIVE_INFINITY : value;
}

/**
 * The tasks the operator asked for.
 *
 * A class-state filter selects only Tasks whose recorded class has that state: a
 * Task with no recorded class is never counted as CPU merely because its class
 * is unknown.
 */
export function selectPlacements(tasks: TaskSummary[], query: PlacementQuery): TaskSummary[] {
  const needle = query.query.trim().toLowerCase();
  return tasks
    .filter(task => {
      if (query.record === 'recorded' && !task.placement) return false;
      if (query.record === 'unrecorded' && task.placement) return false;
      if (query.state !== 'all' && task.placement?.state !== query.state) return false;
      if (!needle) return true;
      const haystack = [task.display_name, task.task_type, task.task_id, task.owner, task.status, placementLabel(task.placement)];
      return haystack.filter(Boolean).join(' ').toLowerCase().includes(needle);
    })
    .sort((a, b) => (query.sort === 'name'
      ? a.display_name.localeCompare(b.display_name)
      : submittedAt(b) - submittedAt(a)));
}

export interface TaskPage<T> {
  rows: T[];
  page: number;
  pages: number;
  total: number;
  first: number;
  last: number;
}

/** One bounded page of rows, so the DOM never grows with the register. */
export function pageOf<T>(items: readonly T[], page: number, size: number): TaskPage<T> {
  const total = items.length;
  const pages = Math.max(1, Math.ceil(total / size));
  const current = Math.min(Math.max(1, Math.trunc(page) || 1), pages);
  const start = (current - 1) * size;
  const rows = items.slice(start, start + size);
  return { rows, page: current, pages, total, first: rows.length ? start + 1 : 0, last: start + rows.length };
}

/** The visible statement of what the table is showing. */
export function pageSummary(page: TaskPage<unknown>): string {
  return page.total ? `Showing ${page.first}–${page.last} of ${page.total} tasks` : 'No tasks match the current filters';
}

const COLUMNS = ['Task', 'Runner', 'Owner', 'Status', 'Execution class', 'Queue', 'Device', 'QoS', 'Constraint', 'Account', 'Exclusive', 'Submitted', 'Walltime'] as const;

export class PlacementAdmin {
  private tasks: TaskSummary[] = [];
  private query: PlacementQuery = { query: '', state: 'all', record: 'all', sort: 'submitted' };
  private size: PlacementPageSize = 50;
  private page = 1;
  private configuration: AdminConfiguration | null = null;
  private failure: string | null = null;
  private readonly body = element('tbody');
  private readonly count = text('span', 'Loading…', 'admin-count');
  private readonly pageState = text('span', '', 'placement-register-state');
  private readonly pager = element('div', 'placement-pager');
  private readonly policy = element('p', 'config-effective');
  private readonly refreshButton = button('Refresh');

  /** The declared mapping, as stored; this surface never re-spells it. */
  setConfiguration(config: AdminConfiguration | null): void {
    this.configuration = config;
    this.renderPolicy();
  }

  async mount(root: HTMLElement): Promise<void> {
    this.refreshButton.addEventListener('click', () => void this.load());

    const search = element('input');
    search.type = 'search';
    search.placeholder = 'Name, Runner, task ID, owner, status, class';
    search.autocomplete = 'off';
    search.addEventListener('input', () => { this.query = { ...this.query, query: search.value }; this.page = 1; this.render(); });
    const state = this.select([['all', 'Any state'], ['cpu', 'CPU'], ['accelerator', 'Accelerator']], value => {
      this.query = { ...this.query, state: value as PlacementState }; this.page = 1; this.render();
    });
    const record = this.select([['all', 'Any record'], ['recorded', 'Recorded'], ['unrecorded', 'Not recorded']], value => {
      this.query = { ...this.query, record: value as PlacementRecord }; this.page = 1; this.render();
    });
    const sort = this.select([['submitted', 'Sort: submitted'], ['name', 'Sort: name']], value => {
      this.query = { ...this.query, sort: value as PlacementSort }; this.page = 1; this.render();
    });
    const size = this.select(PLACEMENT_PAGE_SIZES.map(value => [String(value), `${value} per page`] as [string, string]), value => {
      this.size = Number(value) as PlacementPageSize; this.page = 1; this.render();
    });
    size.value = String(this.size);

    const toolbar = element('div', 'admin-toolbar', [
      element('label', 'admin-field', [text('span', 'Search'), search]),
      element('label', 'admin-field', [text('span', 'Class state'), state]),
      element('label', 'admin-field', [text('span', 'Recorded'), record]),
      element('label', 'admin-field', [text('span', 'Order'), sort]),
      element('label', 'admin-field', [text('span', 'Page size'), size]),
      this.count,
      this.refreshButton,
    ]);

    const head = element('thead');
    head.append(element('tr', '', COLUMNS.map(label => text('th', label))));
    const table = element('table', 'admin-table placement-table');
    table.append(head, this.body);
    const scroll = element('div', 'admin-table-scroll', [table]);

    const heading = element('div', 'admin-section-heading', [
      element('div', '', [
        text('h2', 'Recorded placement'),
        text('p', 'The execution class each Task was placed into, read from its recorded decision. A Task without one stays unrecorded.', 'admin-section-copy'),
      ]),
    ]);
    const policySection = element('section', 'placement-policy-section', [
      text('h2', 'Declared execution classes'),
      text('p', 'The deployment mapping that resolves a stage requirement to a local queue, as the server stores it.', 'admin-section-copy'),
      this.policy,
    ]);

    root.append(policySection, heading, toolbar, scroll, this.pager, this.pageState);
    this.renderPolicy();
    await this.load();
  }

  async load(): Promise<void> {
    setBusy(this.refreshButton, true, 'Refreshing…');
    try {
      this.tasks = await adminApi.listTasks();
      this.failure = null;
    } catch (error) {
      this.tasks = [];
      this.failure = (error as Error).message || 'Unable to load the Task register.';
    } finally {
      setBusy(this.refreshButton, false);
      this.render();
    }
  }

  private select(options: Array<[string, string]>, onChange: (value: string) => void): HTMLSelectElement {
    const control = element('select');
    for (const [value, label] of options) {
      const option = element('option');
      option.value = value;
      option.textContent = label;
      control.append(option);
    }
    control.addEventListener('change', () => onChange(control.value));
    return control;
  }

  private renderPolicy(): void {
    const declared = this.configuration?.resources?.['slurm_execution_classes'];
    const value = declared === null || declared === undefined || declared === '' ? null : String(declared);
    this.policy.textContent = value ?? 'No execution-class mapping is declared.';
  }

  private render(): void {
    const visible = selectPlacements(this.tasks, this.query);
    const view = pageOf(visible, this.page, this.size);
    this.page = view.page;
    this.count.textContent = `${visible.length} of ${this.tasks.length} tasks`;
    this.pageState.textContent = this.failure || pageSummary(view);
    this.pageState.classList.toggle('error-state', Boolean(this.failure));

    this.body.replaceChildren();
    if (this.failure) {
      const cell = element('td', 'admin-empty error-state', [text('span', this.failure)]);
      cell.colSpan = COLUMNS.length;
      this.body.append(element('tr', '', [cell]));
    } else if (!view.rows.length) {
      const cell = element('td', '', [empty('No Tasks match the current filters.')]);
      cell.colSpan = COLUMNS.length;
      this.body.append(element('tr', '', [cell]));
    } else {
      for (const task of view.rows) this.body.append(this.row(task));
    }
    this.renderPager(view);
  }

  private renderPager(view: TaskPage<TaskSummary>): void {
    this.pager.replaceChildren();
    if (!view.total || this.failure) {
      this.pager.hidden = true;
      return;
    }
    this.pager.hidden = false;
    const previous = button('Previous');
    previous.disabled = view.page <= 1;
    previous.addEventListener('click', () => { this.page = view.page - 1; this.render(); });
    const next = button('Next');
    next.disabled = view.page >= view.pages;
    next.addEventListener('click', () => { this.page = view.page + 1; this.render(); });
    this.pager.append(previous, text('span', `Page ${view.page} of ${view.pages}`), next);
  }

  private row(task: TaskSummary): HTMLTableRowElement {
    const placement = task.placement;
    const klass = element('td', 'placement-class');
    if (placement) {
      klass.append(text('code', placementLabel(placement)), text('span', placementStateLabel(placement), 'admin-badge'));
    } else {
      // The explicit unknown: no class, no queue, and no device is asserted for a
      // Task whose recorded decision the server does not have.
      const unknown = text('span', 'Not recorded', 'admin-badge is-unknown');
      unknown.title = 'This Task has no recorded placement decision.';
      klass.append(unknown, text('small', 'No recorded execution class', 'placement-note'));
    }
    const unknownCell = (): HTMLElement => text('td', 'Unknown', 'placement-unknown');
    return element('tr', '', [
      element('td', 'placement-identity', [text('strong', task.display_name), text('code', task.task_id)]),
      text('td', task.task_type),
      text('td', task.owner || 'Not recorded'),
      text('td', task.status),
      klass,
      placement ? text('td', placementQueue(placement)) : unknownCell(),
      placement ? text('td', placementDevice(placement)) : unknownCell(),
      placement ? text('td', placementSchedulerField(placement.qos)) : unknownCell(),
      placement ? text('td', placementSchedulerField(placement.constraint)) : unknownCell(),
      placement ? text('td', placementSchedulerField(placement.account)) : unknownCell(),
      placement ? text('td', placementExclusive(placement)) : unknownCell(),
      text('td', formatDate(task.submitted_at)),
      text('td', task.walltime_seconds === null || task.walltime_seconds === undefined ? 'Not recorded' : formatWalltime(task.walltime_seconds)),
    ]);
  }
}
