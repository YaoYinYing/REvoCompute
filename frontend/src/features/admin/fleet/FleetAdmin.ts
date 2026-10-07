import type { AppShell } from '../../../app/shell';
import { ApiError } from '../../../app/session';
import {
  adminApi,
  idempotencyKey,
  type OperatorAction,
  type OperatorJob,
  type OperatorPlan,
  type RunnerDetail,
  type RunnerFleetEntry,
  type RunnerReadiness,
} from '../api';
import { button, element, empty, formatDate, openDialog, reasonContent, setBusy, text } from '../shared/dom';

/*
 * The Admin Fleet Readiness surface.
 *
 * It reads the control plane's own vocabulary — readiness, capacity, access,
 * the current evidence, the plan for a corrective action, and the Operator Job
 * that runs it — and renders it in the merged Soft Precision language. It does
 * not compute readiness, invent a "PASS" badge for evidence the server does not
 * author, or expose a host path or command: every fact shown comes from the
 * Admin API, and every action is a typed intent whose plan the operator reads
 * before confirming.
 */

/** Human copy for the machine-readable readiness reasons the server emits. */
const REASON_COPY: Record<string, string> = {
  READY: 'Ready to accept new submissions.',
  SIF_MISSING: 'The active Runner image is missing on this deployment.',
  BUILD_PROVENANCE_STALE: 'The active image no longer matches current build inputs.',
  RECEIPT_MISSING: 'No live-test receipt exists for the active image.',
  RECEIPT_STALE: 'The live-test receipt does not match the active Runner identity.',
  RUNTIME_BUNDLE_CHANGED: 'The runtime bundle changed; the image can be reused but needs revalidation.',
  DOCTOR_FAILED: 'The Runner contract failed validation.',
  CONFIGURATION_INVALID: 'The Runner configuration or its build inputs cannot be resolved.',
  RUNNER_UNKNOWN: 'This Runner family is not enabled on this deployment.',
};

const STATUS_LABEL: Record<string, string> = {
  NOT_CONFIGURED: 'Not configured',
  NOT_BUILT: 'Not built',
  BUILD_STALE: 'Build stale',
  NOT_VALIDATED: 'Not validated',
  VALIDATION_STALE: 'Validation stale',
  READY: 'Ready',
};

/** Human copy for an Operator Job's lifecycle, a vocabulary of its own. */
const JOB_STATUS_LABEL: Record<string, string> = {
  QUEUED: 'Queued',
  RUNNING: 'Running',
  SUCCEEDED: 'Succeeded',
  FAILED: 'Failed',
  CANCELLING: 'Cancelling',
  CANCELLED: 'Cancelled',
};

const CAPACITY_COPY: Record<string, string> = {
  scheduler_available: 'Compute available',
  scheduler_busy: 'Compute busy',
  gpu_available: 'GPU available',
  gpu_busy: 'GPU busy',
  capacity_unknown: 'Capacity unknown',
  infrastructure_evidence_unavailable: 'Infrastructure evidence unavailable',
};

const WORKFLOW_LABEL: Record<string, string> = {
  inspect: 'Inspect',
  doctor: 'Doctor',
  prepare: 'Stage candidate',
  build: 'Build image',
  live_test: 'Live validation',
  promote: 'Activate',
  rollback: 'Restore previous',
};

export type FleetFilter = 'all' | 'attention' | 'ready';
export type FleetSort = 'family' | 'status';

export function reasonText(readiness: RunnerReadiness): string {
  return REASON_COPY[readiness.reason_code] || readiness.message || 'No explanation recorded.';
}

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] || status;
}

/** An Operator Job's lifecycle word; job state never shares a readiness badge. */
export function jobStatusLabel(status: string): string {
  return JOB_STATUS_LABEL[status] || status;
}

export function capacityLabel(reason: string, available: boolean | null | undefined): string {
  if (CAPACITY_COPY[reason]) return CAPACITY_COPY[reason]!;
  return available === null || available === undefined ? 'Unknown' : available ? 'Available' : 'Busy';
}

export function workflowLabel(stage: string): string {
  return WORKFLOW_LABEL[stage] || stage;
}

/** Filter and order the fleet by the operator's current view. */
export function filterFleet(
  rows: RunnerFleetEntry[],
  { query, filter, sort }: { query: string; filter: FleetFilter; sort: FleetSort },
): RunnerFleetEntry[] {
  const needle = query.trim().toLowerCase();
  return rows
    .filter(row => {
      if (needle && !row.runner_family.toLowerCase().includes(needle)) return false;
      if (filter === 'ready') return row.readiness.status === 'READY';
      if (filter === 'attention') return row.readiness.status !== 'READY';
      return true;
    })
    .sort((a, b) => (sort === 'family'
      ? a.runner_family.localeCompare(b.runner_family)
      : a.readiness.status.localeCompare(b.readiness.status) || a.runner_family.localeCompare(b.runner_family)));
}

function statusBadge(status: string): HTMLElement {
  const badge = text('span', statusLabel(status), 'admin-badge');
  badge.dataset.status = status;
  if (status === 'READY') badge.classList.add('is-good');
  else if (status === 'NOT_CONFIGURED' || status === 'NOT_BUILT') badge.classList.add('is-muted');
  else badge.classList.add('is-attention');
  return badge;
}

/** A job lifecycle badge: its own word, its own status axis, its own colour. */
function jobStatusBadge(status: string): HTMLElement {
  const badge = text('span', jobStatusLabel(status), 'admin-badge');
  badge.dataset.jobStatus = status;
  if (status === 'SUCCEEDED') badge.classList.add('is-good');
  else if (status === 'QUEUED' || status === 'RUNNING') badge.classList.add('is-muted');
  else badge.classList.add('is-attention');
  return badge;
}

function field(label: string, value: string, className = ''): HTMLElement {
  const row = element('div', `fleet-fact ${className}`.trim());
  row.append(text('dt', label), text('dd', value || '—'));
  return row;
}

export class FleetAdmin {
  private rows: RunnerFleetEntry[] = [];
  private executor: { available: boolean; reason: string } | null = null;
  private filter: FleetFilter = 'all';
  private sort: FleetSort = 'family';
  private query = '';
  private table = element('tbody');
  private count = text('span', 'Loading…', 'admin-count');
  private executorBanner = element('p', 'fleet-executor');
  private refreshButton = button('Refresh');
  private readonly detail = element('section', 'fleet-detail');

  constructor(private readonly shell: AppShell) {}

  async mount(root: HTMLElement): Promise<void> {
    const heading = element('div', 'admin-section-heading');
    const copy = element('div', '');
    copy.append(text('h2', 'Runner fleet'), text('p', 'Derived readiness, transient capacity, and access for every enabled Runner family.', 'admin-section-copy'));
    heading.append(copy, this.refreshButton);
    this.refreshButton.addEventListener('click', () => void this.load());

    const toolbar = element('div', 'admin-toolbar');
    const search = element('input');
    search.type = 'search';
    search.placeholder = 'Filter by family name';
    search.autocomplete = 'off';
    search.addEventListener('input', () => { this.query = search.value.trim().toLowerCase(); this.renderTable(); });
    const filter = element('select');
    for (const [value, label] of [['all', 'All families'], ['attention', 'Needs attention'], ['ready', 'Ready']] as Array<[FleetFilter, string]>) {
      const option = element('option'); option.value = value; option.textContent = label; filter.append(option);
    }
    filter.addEventListener('change', () => { this.filter = filter.value as FleetFilter; this.renderTable(); });
    const sort = element('select');
    for (const [value, label] of [['family', 'Sort: family'], ['status', 'Sort: status']] as Array<[FleetSort, string]>) {
      const option = element('option'); option.value = value; option.textContent = label; sort.append(option);
    }
    sort.addEventListener('change', () => { this.sort = sort.value as FleetSort; this.renderTable(); });

    toolbar.append(
      element('label', 'admin-field', [text('span', 'Search'), search]),
      element('label', 'admin-field', [text('span', 'Readiness'), filter]),
      element('label', 'admin-field', [text('span', 'Order'), sort]),
      this.count,
    );

    const scroll = element('div', 'admin-table-scroll');
    const table = element('table', 'admin-table');
    const head = element('thead');
    const headRow = element('tr');
    for (const label of ['Runner family', 'Readiness', 'Capacity', 'Access', 'In flight']) headRow.append(text('th', label));
    head.append(headRow);
    table.append(head, this.table);
    scroll.append(table);

    root.append(heading, this.executorBanner, toolbar, scroll, this.detail);
    await this.load();
  }

  async load(): Promise<void> {
    setBusy(this.refreshButton, true, 'Refreshing…');
    try {
      const fleet = await adminApi.getRunnerFleet();
      this.rows = fleet.runners;
      this.executor = fleet.executor;
      this.renderExecutor();
      this.renderTable();
    } catch (error) {
      this.rows = [];
      this.table.replaceChildren();
      this.table.append(element('tr', '', [element('td', '', [empty((error as Error).message || 'Unable to load the fleet.', true)])]));
    } finally {
      setBusy(this.refreshButton, false);
    }
  }

  private renderExecutor(): void {
    if (!this.executor) return;
    this.executorBanner.replaceChildren();
    this.executorBanner.classList.toggle('is-warning', !this.executor.available);
    this.executorBanner.append(
      text('strong', this.executor.available ? 'Operator executor available' : 'Operator executor unavailable'),
      text('span', this.executor.available
        ? ' Host operations can be planned and run from this interface.'
        : ' Readiness, capacity, access, and history stay available; mutating actions are disabled until the host executor is reachable.'),
    );
  }

  private visible(): RunnerFleetEntry[] {
    return filterFleet(this.rows, { query: this.query, filter: this.filter, sort: this.sort });
  }

  private renderTable(): void {
    const rows = this.visible();
    this.count.textContent = `${rows.length} of ${this.rows.length} famil${this.rows.length === 1 ? 'y' : 'ies'}`;
    this.table.replaceChildren();
    if (!rows.length) {
      this.table.append(element('tr', '', [element('td', '', [empty('No Runner families match the current filters.')])]));
      return;
    }
    for (const row of rows) this.table.append(this.renderRow(row));
  }

  private renderRow(row: RunnerFleetEntry): HTMLTableRowElement {
    const tr = element('tr');
    tr.dataset.family = row.runner_family;
    tr.dataset.status = row.readiness.status;

    const name = element('td', 'fleet-identity');
    const open = button(row.runner_family, 'fleet-open');
    open.addEventListener('click', () => void this.openDetail(row.runner_family));
    name.append(open, text('small', row.readiness.next_action === 'none' ? 'No action required' : `Recommended: ${workflowLabel(row.readiness.next_action)}`));

    const readiness = element('td');
    readiness.append(statusBadge(row.readiness.status), text('small', reasonText(row.readiness)));

    const capacity = element('td');
    capacity.append(text('span', capacityLabel(row.capacity.reason, row.capacity.available), `admin-badge ${row.capacity.available ? 'is-good' : ''}`.trim()));

    const access = element('td');
    access.append(text('span', row.access.restricted ? (row.access.granted ? 'Granted' : 'Restricted') : 'Open', 'admin-badge'));

    const flight = element('td');
    flight.append(row.in_flight
      ? text('span', `${workflowLabel(row.in_flight.action.replace('runner.', ''))} · ${row.in_flight.status}`, 'admin-badge is-attention')
      : text('span', 'Idle', 'admin-badge'));

    tr.append(name, readiness, capacity, access, flight);
    return tr;
  }

  private async openDetail(family: string): Promise<void> {
    this.detail.replaceChildren(text('p', 'Loading Runner evidence…', 'admin-empty'));
    try {
      const detail = await adminApi.getRunnerDetail(family);
      this.renderDetail(detail);
    } catch (error) {
      this.detail.replaceChildren(empty((error as Error).message || 'Unable to load Runner detail.', true));
    }
  }

  private renderDetail(detail: RunnerDetail): void {
    const panel = element('article', 'fleet-detail-panel');
    const head = element('header', 'admin-section-heading');
    const title = element('div', '');
    title.append(text('h2', detail.runner_family), text('p', reasonText(detail.readiness), 'admin-section-copy'));
    head.append(title, statusBadge(detail.readiness.status));

    const facts = element('dl', 'fleet-facts');
    const evidence = detail.readiness.evidence;
    facts.append(
      field('Active image', evidence.sif_exists ? 'Present' : 'Missing'),
      field('Build provenance', evidence.build_provenance_current ? 'Current' : 'Stale'),
      field('Runtime bundle', evidence.runtime_bundle_sha256 ? 'Pinned' : 'None'),
      field('Live receipt', evidence.receipt_valid ? 'Valid' : evidence.receipt_exists ? 'Stale' : 'Missing'),
      field('Last validated', evidence.receipt_tested_at ? formatDate(evidence.receipt_tested_at) : 'Never'),
      field('Smoke coverage', `${evidence.passed_smoke_cases?.length ?? 0} of ${evidence.required_smoke_cases?.length ?? 0} cases`),
      field('Capacity', capacityLabel(detail.capacity.reason, detail.capacity.available)),
      field('Access', detail.access.restricted ? (detail.access.granted ? 'Granted' : 'Restricted') : 'Open'),
    );

    const actions = element('div', 'fleet-actions');
    actions.append(text('h3', 'Corrective actions'));
    const list = element('div', 'fleet-action-list');
    for (const action of detail.actions) list.append(this.renderAction(detail, action));
    actions.append(list);

    const history = element('div', 'fleet-history');
    history.append(text('h3', 'Operator history'));
    const historyList = element('div', 'fleet-history-list');
    historyList.append(text('p', 'Loading history…', 'admin-empty'));
    history.append(historyList);

    const close = button('Close');
    close.addEventListener('click', () => this.detail.replaceChildren());
    panel.append(head, facts, actions, history, close);
    this.detail.replaceChildren(panel);
    void this.loadHistory(detail.runner_family, historyList);
  }

  private renderAction(detail: RunnerDetail, action: OperatorAction): HTMLElement {
    const item = element('div', 'fleet-action');
    const plan = action.plan as OperatorPlan | null | undefined;
    const summary = element('div', 'fleet-action-copy');
    summary.append(
      text('strong', workflowLabel(action.id.replace('runner.', ''))),
      text('small', plan && plan.effective_actions.length
        ? plan.effective_actions.map(stage => workflowLabel(stage)).join(' → ')
        : action.summary),
    );
    item.append(summary);

    if (!action.available || !plan) {
      item.append(text('span', 'Not available for the current state', 'admin-badge is-muted'));
      return item;
    }
    const run = button(action.tier === 'activate' ? 'Review and activate' : 'Review and run', action.tier === 'read' ? 'secondary-button' : 'primary-button');
    run.disabled = !this.executor?.available && action.tier !== 'read';
    run.addEventListener('click', () => void this.confirmAndRun(detail, action, plan));
    item.append(run);
    return item;
  }

  private async confirmAndRun(detail: RunnerDetail, action: OperatorAction, plan: OperatorPlan): Promise<void> {
    // The plan is shown in full before confirmation: what will run, what will
    // not, and which evidence identity it is bound to.
    const body = element('div', 'admin-dialog-fields');
    body.append(text('p', `Current state: ${statusLabel(plan.current_state)}. ${reasonText(detail.readiness)}`, 'admin-dialog-copy'));
    const willRun = element('ul', 'fleet-plan-list');
    for (const effect of plan.expected_effects) willRun.append(text('li', effect));
    body.append(text('h4', 'This plan will'), willRun);
    if (plan.not_required.length) {
      const willNot = element('ul', 'fleet-plan-list is-muted');
      for (const item of plan.not_required) willNot.append(text('li', item.label));
      body.append(text('h4', 'This plan will not'), willNot);
    }
    if (plan.cli_reference) body.append(text('p', `CLI equivalent (reference only): ${plan.cli_reference}`, 'admin-dialog-copy is-mono'));

    const confirmation = plan.requires_confirmation ? plan.runner_family : undefined;
    const { root, confirmation: confirmationInput } = reasonContent(
      plan.requires_confirmation
        ? 'This action changes the active artifact. Confirm to continue.'
        : 'Confirm to run this bounded operator action.',
      confirmation,
    );
    body.append(root);

    const confirmed = await openDialog<boolean>({
      title: `${workflowLabel(action.id.replace('runner.', ''))} — ${plan.runner_family}`,
      content: body,
      confirmLabel: 'Run',
      destructive: action.tier === 'activate',
      validate: () => (confirmationInput && confirmationInput.value.trim() !== confirmation ? `Type ${confirmation} to confirm` : null),
    });
    if (confirmed === null) return;

    try {
      const accepted = await adminApi.runRunnerAction(plan.runner_family, action.id, plan.plan_digest, idempotencyKey(action.id));
      this.detail.dataset.jobId = accepted.job.job_id || '';
      this.shell.notify(`${workflowLabel(action.id.replace('runner.', ''))} accepted for ${plan.runner_family}.`);
      await this.openDetail(plan.runner_family);
    } catch (error) {
      const message = error instanceof ApiError && error.status === 409
        ? 'State changed; review the new plan.'
        : (error as Error).message || 'The operator action was rejected.';
      this.detail.replaceChildren(empty(message, true));
      await this.openDetail(plan.runner_family).catch(() => undefined);
    }
  }

  private async loadHistory(family: string, target: HTMLElement): Promise<void> {
    try {
      const history = await adminApi.getRunnerHistory(family, 25);
      target.replaceChildren();
      if (!history.length) {
        target.append(empty('No operator actions recorded for this family yet.'));
        return;
      }
      for (const job of history) target.append(this.renderHistory(job));
    } catch (error) {
      target.replaceChildren(empty((error as Error).message || 'Unable to load history.', true));
    }
  }

  private renderHistory(job: OperatorJob): HTMLElement {
    const row = element('div', 'fleet-history-row');
    const head = element('div', '');
    head.append(text('strong', job.action), jobStatusBadge(job.status));
    const detail: string[] = [formatDate(job.finished_at || job.created_at)];
    if (job.actor_username) detail.push(job.actor_username);
    const effect = job.effect;
    if (effect?.effective_actions?.length) {
      // Requested intent is recorded beside the actions that actually ran, so a
      // repair that only revalidated is not read as a full repair.
      detail.push(`${effect.requested_intent} → ${effect.effective_actions.join(', ')}`);
    }
    if (job.failure_category) detail.push(`failure: ${job.failure_category}`);
    head.append(text('small', detail.join(' · ')));
    row.append(head);
    return row;
  }
}
