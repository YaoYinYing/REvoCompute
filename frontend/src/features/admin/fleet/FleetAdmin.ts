import type { AppShell } from '../../../app/shell';
import { ApiError } from '../../../app/session';
import {
  adminApi,
  idempotencyKey,
  type OperatorAction,
  type OperatorJob,
  type OperatorPlan,
  type RunnerDetail,
  type RunnerFleet,
  type RunnerFleetEntry,
  type RunnerReadiness,
} from '../api';
import { button, element, empty, formatDate, openDialog, reasonContent, setBusy, text } from '../../../components/dom';

/*
 * Runner Management.
 *
 * It reads the control plane's own vocabulary — readiness, capacity, access,
 * the current evidence, the plan for a corrective action, and the Operator Job
 * that runs it — and renders it in the merged Soft Precision language. It does
 * not compute readiness, invent a "PASS" badge for evidence the server does not
 * author, or expose a host path or command: every fact shown comes from the
 * Admin API, and every action is a typed intent whose plan the operator reads
 * before confirming.
 *
 * Four facts stay apart, because collapsing any pair of them would state
 * something the server did not:
 *
 * * a family's readiness verdict is derived evidence about its artifact;
 * * its capacity is transient execution availability;
 * * its access is who may submit to it;
 * * the Operator executor is a host capability that gates every mutating action
 *   for every family at once.
 *
 * The executor is therefore reported once, above the register, and never folded
 * into a family's own state; and the summary counts the server's verdicts rather
 * than being a readiness verdict of its own.
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

/**
 * The four bands a readiness verdict is summarized into.
 *
 * These are groupings of the server's own six verdicts, not verdicts of their
 * own: nothing is derived here, and a family is counted in exactly one band by
 * its ``readiness.status``. ``unavailable`` and ``stale_build`` are separated
 * because they need different work — a family with no usable artifact cannot be
 * validated, while a stale build is a rebuild — so an operator reads what to do
 * next from the order rather than from a single count.
 */
export const WEAKNESSES = ['unavailable', 'stale_build', 'needs_attention', 'ready'] as const;
export type Weakness = (typeof WEAKNESSES)[number];

const WEAKNESS_LABEL: Record<Weakness, string> = {
  unavailable: 'Unavailable',
  stale_build: 'Stale build',
  needs_attention: 'Needs attention',
  ready: 'Ready',
};

/** Why a family sits in its band: the ordering an operator acts on. */
const WEAKNESS_COPY: Record<Weakness, string> = {
  unavailable: 'No usable image is active on this deployment.',
  stale_build: 'Rebuild the image, then validate it.',
  needs_attention: 'The image exists and needs (re)validation.',
  ready: 'Accepting new submissions.',
};

/** The band a readiness verdict is grouped into; never a second verdict. */
export function weaknessOf(status: string): Weakness {
  if (status === 'NOT_CONFIGURED' || status === 'NOT_BUILT') return 'unavailable';
  if (status === 'BUILD_STALE') return 'stale_build';
  if (status === 'READY') return 'ready';
  return 'needs_attention';
}

const WEAKNESS_RANK: Record<Weakness, number> = {
  unavailable: 0,
  stale_build: 1,
  needs_attention: 2,
  ready: 3,
};

export interface FleetSummaryEntry {
  weakness: Weakness;
  label: string;
  count: number;
  reason: string;
}

/**
 * The register summarized by the server's own verdicts, in actionable order.
 *
 * The total is returned beside the bands so an empty register is distinguishable
 * from a register that is entirely healthy, and a band with no member is still
 * shown: "no family is unavailable" is a fact worth reading, not an omission.
 */
export function summarizeFleet(rows: RunnerFleetEntry[]): { total: number; entries: FleetSummaryEntry[] } {
  const counts: Record<Weakness, number> = { unavailable: 0, stale_build: 0, needs_attention: 0, ready: 0 };
  for (const row of rows) counts[weaknessOf(row.readiness.status)] += 1;
  return {
    total: rows.length,
    entries: WEAKNESSES.map(weakness => ({
      weakness,
      label: WEAKNESS_LABEL[weakness],
      count: counts[weakness],
      reason: WEAKNESS_COPY[weakness],
    })),
  };
}

/** One line stating where the register stands, or that it is empty. */
export function summarySentence(rows: RunnerFleetEntry[]): string {
  const { total, entries } = summarizeFleet(rows);
  if (!total) return 'No Runner family is enabled on this deployment.';
  const needing = entries.filter(entry => entry.weakness !== 'ready').reduce((sum, entry) => sum + entry.count, 0);
  const families = total === 1 ? '1 enabled Runner family' : `${total} enabled Runner families`;
  if (!needing) return `All ${families} ${total === 1 ? 'is' : 'are'} ready.`;
  return `${needing} of ${families} need${needing === 1 ? 's' : ''} work before accepting new submissions.`;
}

export type FleetFilter = 'all' | 'attention' | 'ready';
export type FleetSort = 'attention' | 'family' | 'status';

export function reasonText(readiness: RunnerReadiness): string {
  return REASON_COPY[readiness.reason_code] || readiness.message || 'No explanation recorded.';
}

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] || status;
}

/** The human band name a readiness verdict is grouped into. */
export function weaknessLabel(status: string): string {
  return WEAKNESS_LABEL[weaknessOf(status)];
}

function shortIdentity(sha256: string): string {
  const digest = sha256.startsWith('sha256:') ? sha256.slice('sha256:'.length) : sha256;
  return digest.length > 12 ? `${digest.slice(0, 12)}…` : digest;
}

/** Why the server could not establish the installed artifact's identity. */
const ACTIVE_IMAGE_UNKNOWN_COPY: Record<string, string> = {
  STAGED_CANDIDATE_PENDING: 'a staged candidate is awaiting activation',
  ACTIVE_IMAGE_IDENTITY_UNKNOWN: 'the server has not established an identity',
};

/**
 * The active artifact's server-established identity, or the reason it is unknown.
 *
 * The server projects ``active_image`` from the same evidence the readiness
 * verdict was derived from. This reads that projection and never falls back to
 * "the file exists": an artifact whose identity was not established is
 * ``Unknown``, because presence is not identity.
 */
export function activeImageLabel(readiness: RunnerReadiness): string {
  const image = readiness.active_image;
  if (!image || image.state === 'UNKNOWN') return 'Unknown';
  if (image.state === 'MISSING') return 'Missing';
  return image.sha256 ? `Active · ${shortIdentity(image.sha256)}` : 'Unknown';
}

/** The full active identity for the evidence dialog; never a presence claim. */
export function activeImageDetail(readiness: RunnerReadiness): string {
  const image = readiness.active_image;
  if (image?.state === 'MISSING') return 'Missing';
  if (image?.state !== 'ACTIVE' || !image.sha256) {
    const reason = image?.reason_code ? ACTIVE_IMAGE_UNKNOWN_COPY[image.reason_code] : undefined;
    return reason ? `Unknown — ${reason}` : 'Unknown — the server has not established an identity';
  }
  return `Active · ${image.sha256}`;
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

/**
 * What the host-executor banner says, given the server's own executor state.
 *
 * The server's ``unavailable_reason`` is the actionable sentence — it names the
 * missing artifact by role and the corrective step (run the operation with
 * ``run/restart.sh`` on the deployment host) — so it is rendered verbatim rather
 * than replaced by a constant "unavailable". The fallback is only for an older
 * server that reported no sentence, and it must still say what stays available.
 */
export function executorNotice(executor: RunnerFleet['executor']): { title: string; detail: string } {
  if (executor.available) {
    return {
      title: 'Host executor available',
      detail: ' Mutating Runner actions can be planned and run from this interface for every family below.',
    };
  }
  return {
    title: 'Host executor unavailable',
    detail: ` ${executor.unavailable_reason || 'Readiness, capacity, access, and history stay available; mutating actions are disabled until the host executor is reachable.'}`,
  };
}

/**
 * Filter and order the register by the operator's current view.
 *
 * The default order is by how much work a family needs: a family that cannot
 * accept submissions at all sorts above one that is merely unvalidated, and a
 * ready family sorts last. Ordering by name or by raw status stays available —
 * the attention order is a default, not the only reading.
 */
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
    .sort((a, b) => {
      if (sort === 'family') return a.runner_family.localeCompare(b.runner_family);
      if (sort === 'status') return a.readiness.status.localeCompare(b.readiness.status) || a.runner_family.localeCompare(b.runner_family);
      return WEAKNESS_RANK[weaknessOf(a.readiness.status)] - WEAKNESS_RANK[weaknessOf(b.readiness.status)]
        || a.runner_family.localeCompare(b.runner_family);
    });
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
  private executor: RunnerFleet['executor'] | null = null;
  private filter: FleetFilter = 'all';
  private sort: FleetSort = 'attention';
  private query = '';
  private table = element('tbody');
  private count = text('span', 'Loading…', 'admin-count');
  private executorBanner = element('aside', 'fleet-executor');
  private summary = element('section', 'fleet-summary');
  private refreshButton = button('Refresh');
  private readonly detail = element('dialog', 'fleet-detail fleet-evidence-dialog');
  private detailGeneration = 0;
  private detailPhase = 'Lifecycle';

  constructor(private readonly shell: AppShell) {}

  async mount(root: HTMLElement): Promise<void> {
    this.refreshButton.addEventListener('click', () => void this.load());

    const toolbar = element('div', 'admin-toolbar');
    const search = element('input');
    search.type = 'search';
    search.placeholder = 'Filter by family name';
    search.autocomplete = 'off';
    search.addEventListener('input', () => { this.query = search.value.trim().toLowerCase(); this.renderTable(); });
    const filter = element('select');
    for (const [value, label] of [['all', 'All families'], ['attention', 'Needs work'], ['ready', 'Ready']] as Array<[FleetFilter, string]>) {
      const option = element('option'); option.value = value; option.textContent = label; filter.append(option);
    }
    filter.addEventListener('change', () => { this.filter = filter.value as FleetFilter; this.renderTable(); });
    const sort = element('select');
    for (const [value, label] of [['attention', 'Order: most work first'], ['family', 'Order: family'], ['status', 'Order: verdict']] as Array<[FleetSort, string]>) {
      const option = element('option'); option.value = value; option.textContent = label; sort.append(option);
    }
    sort.addEventListener('change', () => { this.sort = sort.value as FleetSort; this.renderTable(); });

    toolbar.append(
      element('label', 'admin-field', [text('span', 'Search'), search]),
      element('label', 'admin-field', [text('span', 'Readiness'), filter]),
      element('label', 'admin-field', [text('span', 'Order'), sort]),
      this.count,
      this.refreshButton,
    );

    const scroll = element('div', 'admin-table-scroll');
    const table = element('table', 'admin-table');
    const head = element('thead');
    const headRow = element('tr');
    for (const label of ['Runner family', 'Build', 'Live test', 'Active image', 'Freshness']) headRow.append(text('th', label));
    head.append(headRow);
    table.append(head, this.table);
    scroll.append(table);

    // The summary sits above the register, the executor banner above the summary:
    // a host-wide capability is read once, while a family's own work is read in
    // the band its verdict falls in.
    root.append(this.executorBanner, this.summary, toolbar, scroll, this.detail);
    await this.load();
  }

  async load(): Promise<void> {
    setBusy(this.refreshButton, true, 'Refreshing…');
    try {
      const fleet = await adminApi.getRunnerFleet();
      this.rows = fleet.runners;
      this.executor = fleet.executor;
      this.renderExecutor();
      this.renderSummary();
      this.renderTable();
    } catch (error) {
      this.rows = [];
      this.summary.replaceChildren();
      this.table.replaceChildren();
      this.table.append(element('tr', '', [element('td', '', [empty((error as Error).message || 'Unable to load the Runner register.', true)])]));
    } finally {
      setBusy(this.refreshButton, false);
    }
  }

  /** The Operator executor's own state, above the register and never folded in. */
  private renderExecutor(): void {
    if (!this.executor) return;
    const notice = executorNotice(this.executor);
    this.executorBanner.replaceChildren();
    this.executorBanner.classList.toggle('is-warning', !this.executor.available);
    const evidence = element('details'); evidence.append(text('summary', 'Host capability evidence'), text('p', notice.detail));
    this.executorBanner.append(text('strong', notice.title), text('span', this.executor.available ? ' Supported host operations are available.' : ' Viewing evidence only.'), evidence);
  }

  /**
   * The register's verdicts, counted and ordered by how much work each needs.
   *
   * Each band is the server's own verdicts grouped, with its count and the work
   * it implies: an operator reads what to do next from the order, not from a
   * single health number this view would have to invent.
   */
  private renderSummary(): void {
    this.summary.replaceChildren();
    if (!this.rows.length) {
      this.summary.append(text('h2', 'Runner families'), empty('No Runner family is enabled on this deployment. Nothing can be submitted until one is enabled by an administrator.'));
      return;
    }
    const { total, entries } = summarizeFleet(this.rows);
    this.summary.append(text('h2', 'Runner families'));
    this.summary.append(text('p', summarySentence(this.rows), 'fleet-summary-line'));
    const list = element('div', 'fleet-summary-bands');
    for (const entry of entries) {
      const band = element('div', `fleet-band is-${entry.weakness}`);
      band.dataset.band = entry.weakness;
      band.append(
        text('span', entry.label, 'fleet-band-label'),
        text('strong', String(entry.count), 'fleet-band-count'),
        text('span', entry.reason, 'fleet-band-copy'),
      );
      band.setAttribute('role', 'group');
      band.setAttribute('aria-label', `${entry.label}: ${entry.count} of ${total}`);
      list.append(band);
    }
    this.summary.append(list);
  }

  private visible(): RunnerFleetEntry[] {
    return filterFleet(this.rows, { query: this.query, filter: this.filter, sort: this.sort });
  }

  private renderTable(): void {
    const rows = this.visible();
    this.count.textContent = `${rows.length} of ${this.rows.length} famil${this.rows.length === 1 ? 'y' : 'ies'}`;
    this.table.replaceChildren();
    if (!rows.length) {
      // An empty register and an over-filtered one are different states, and a
      // filter that matches nothing says so rather than reading as an empty fleet.
      const message = this.rows.length
        ? 'No Runner family matches the current filters. Clear the search or choose All families.'
        : 'No Runner family is enabled on this deployment.';
      this.table.append(element('tr', '', [element('td', '', [empty(message)])]));
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

    const evidence = row.readiness.evidence;
    const cell = (label: string, phase: string): HTMLTableCellElement => {
      const td = element('td'); const control = button(label, 'fleet-evidence-cell');
      control.setAttribute('aria-label', `${row.runner_family} · ${phase}: ${label}`);
      control.addEventListener('click', () => void this.openDetail(row.runner_family, phase)); td.append(control); return td;
    };
    const known = (value: boolean | undefined, yes: string, no: string) => value === true ? yes : value === false ? no : 'Unknown';
    const build = cell(known(evidence.sif_exists, 'Built', 'Not built'), 'Build');
    const test = cell(evidence.receipt_valid === true ? 'Validated' : evidence.receipt_exists === true ? 'Receipt stale' : known(evidence.receipt_exists, 'Recorded', 'No receipt'), 'Live test');
    const active = cell(activeImageLabel(row.readiness), 'Active image');
    const freshness = cell(statusLabel(row.readiness.status), 'Freshness');
    if (row.in_flight) name.append(text('small', `Management operation: ${workflowLabel(row.in_flight.action.replace('runner.', ''))} · ${row.in_flight.status}`));
    tr.append(name, build, test, active, freshness);
    return tr;
  }

  private async openDetail(family: string, phase = 'Lifecycle'): Promise<void> {
    this.detailPhase = phase;
    const generation = ++this.detailGeneration;
    const cancel = button('Close'); cancel.addEventListener('click', () => this.detail.close());
    this.detail.setAttribute('aria-label', `${family} — ${phase} evidence`);
    this.detail.replaceChildren(text('p', 'Loading Runner evidence…', 'admin-empty'), cancel);
    if (!this.detail.open) this.detail.showModal();
    try {
      const detail = await adminApi.getRunnerDetail(family);
      if (generation === this.detailGeneration && this.detail.open) this.renderDetail(detail);
    } catch (error) {
      if (generation === this.detailGeneration && this.detail.open) this.detail.replaceChildren(empty((error as Error).message || 'Unable to load Runner detail.', true), cancel);
    }
  }

  private renderDetail(detail: RunnerDetail): void {
    const panel = element('article', 'fleet-detail-panel');
    const head = element('header', 'admin-section-heading');
    const title = element('div', '');
    title.append(text('h2', `${detail.runner_family} · ${this.detailPhase} evidence`), text('p', reasonText(detail.readiness), 'admin-section-copy'));
    head.append(title, statusBadge(detail.readiness.status));

    // Derived evidence first: every field is a fact the server read, and each is
    // shown as the evidence it is rather than as a second verdict.
    const evidence = detail.readiness.evidence;
    const facts = element('dl', 'fleet-facts');
    facts.append(
      field('Readiness verdict', statusLabel(detail.readiness.status)),
      field('Recommended next step', detail.readiness.next_action === 'none' ? 'None' : workflowLabel(detail.readiness.next_action)),
      field('Active image', activeImageDetail(detail.readiness)),
      field('Build provenance', evidence.build_provenance_current ? 'Current' : 'Stale'),
      field('Runtime bundle', evidence.runtime_bundle_sha256 ? 'Pinned' : 'None'),
      field('Live receipt', evidence.receipt_valid ? 'Valid' : evidence.receipt_exists ? 'Stale' : 'Missing'),
      field('Last validated', evidence.receipt_tested_at ? formatDate(evidence.receipt_tested_at) : 'Never'),
      field('Smoke coverage', evidence.required_smoke_cases?.length
        ? `${evidence.passed_smoke_cases?.length ?? 0} of ${evidence.required_smoke_cases.length} cases`
        : 'No cases declared'),
      // Capacity and access remain their own facts beside the verdict above them:
      // a ready family with no free compute is not a broken family.
      field('Capacity (transient)', capacityLabel(detail.capacity.reason, detail.capacity.available)),
      field('Access', detail.access.restricted ? (detail.access.granted ? 'Restricted · granted to you' : 'Restricted · not granted') : 'Open to all users'),
      field('Host executor', this.executor ? (this.executor.available ? 'Available' : 'Unavailable') : 'Unknown'),
    );

    const actions = element('div', 'fleet-actions');
    actions.append(text('h3', 'Corrective actions'));
    const list = element('div', 'fleet-action-list');
    for (const action of detail.actions.filter(action => action.tier !== 'activate' && !/promote|rollback|activate|restore/i.test(action.id))) list.append(this.renderAction(detail, action));
    actions.append(list);

    const history = element('div', 'fleet-history');
    history.append(text('h3', 'Operator history'));
    const historyList = element('div', 'fleet-history-list');
    historyList.append(text('p', 'Loading history…', 'admin-empty'));
    history.append(historyList);

    const close = button('Close');
    close.addEventListener('click', () => this.detail.close());
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
