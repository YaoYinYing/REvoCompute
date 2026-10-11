import type { AppShell } from '../../../app/shell';
import { adminApi, type AdminConfiguration, type ConfigValue, type TaskCatalog, type TaskTypeConfig } from '../api';
import { PlacementAdmin } from '../placement/PlacementAdmin';
import { button, element, empty, formatDate, setBusy, text } from '../shared/dom';
import { mountTabs } from '../shared/tabs';

type FieldDefinition = { key: keyof TaskTypeConfig; label: string; type?: 'text' | 'number' | 'boolean'; placeholder?: string };

const baseTaskFields: FieldDefinition[] = [
  { key: 'cpus', label: 'CPU cores', type: 'number' },
  { key: 'memory', label: 'Memory', placeholder: 'e.g. 16G' },
  { key: 'max_runtime_seconds', label: 'Maximum runtime', placeholder: '1:00:00 or 3600' },
];
const slurmTaskFields: FieldDefinition[] = [
  { key: 'slurm_partition', label: 'Partition' }, { key: 'slurm_gres', label: 'GRES' },
  { key: 'slurm_nodes', label: 'Nodes', type: 'number' }, { key: 'slurm_ntasks', label: 'Tasks', type: 'number' },
  { key: 'slurm_qos', label: 'QOS' }, { key: 'slurm_account', label: 'Account' },
  { key: 'slurm_constraint', label: 'Constraint' }, { key: 'slurm_exclusive', label: 'Exclusive', type: 'boolean' },
];

const globalFields: Array<{ key: string; label: string; description: string }> = [
  { key: 'cpus', label: 'CPU cores', description: 'Default CPU allocation per scientific task' },
  { key: 'memory', label: 'Memory', description: 'Default task memory, for example 4G or 16000M' },
  { key: 'max_runtime_seconds', label: 'Maximum runtime', description: 'Default wall-clock limit in seconds' },
  { key: 'slurm_partition', label: 'SLURM partition', description: 'Default scheduler partition when no task override exists' },
  { key: 'slurm_gres', label: 'SLURM GRES', description: 'Default generic resource request for GPU task types' },
  { key: 'slurm_nodes', label: 'SLURM nodes', description: 'Default node count' },
  { key: 'slurm_ntasks', label: 'SLURM tasks', description: 'Default task count' },
  { key: 'slurm_qos', label: 'SLURM QOS', description: 'Default quality of service' },
  { key: 'slurm_account', label: 'SLURM account', description: 'Default scheduler account' },
  { key: 'slurm_constraint', label: 'SLURM constraint', description: 'Default scheduler constraint' },
  { key: 'slurm_exclusive', label: 'SLURM exclusive', description: 'Whether tasks request exclusive allocation' },
];

export function parseRuntime(value: string): number | null {
  const normalized = value.trim();
  if (!normalized) return null;
  const parts = normalized.split(':');
  if (parts.length === 3) {
    const [hours, minutes, seconds] = parts.map(Number);
    if ([hours, minutes, seconds].every(Number.isFinite) && minutes! >= 0 && minutes! < 60 && seconds! >= 0 && seconds! < 60) return Math.round(hours! * 3600 + minutes! * 60 + seconds!);
  }
  const numeric = Number(normalized);
  return Number.isFinite(numeric) && numeric >= 0 ? Math.round(numeric) : null;
}

function fieldValue(config: TaskTypeConfig, definition: FieldDefinition, control: HTMLInputElement | HTMLSelectElement): ConfigValue {
  const raw = control.value.trim();
  if (!raw) return null;
  if (definition.type === 'boolean') return raw === 'true';
  if (definition.key === 'max_runtime_seconds') return parseRuntime(raw);
  if (definition.type === 'number') {
    const value = Number(raw);
    return Number.isFinite(value) ? value : raw;
  }
  return raw;
}

export class ConfigurationAdmin {
  private config: AdminConfiguration | null = null;
  private catalog: TaskCatalog | null = null;
  private taskPanel = element('section', 'admin-tab-panel');
  private resourcePanel = element('section', 'admin-tab-panel');
  private infrastructurePanel = element('section', 'admin-tab-panel');
  private placementPanel = element('section', 'admin-tab-panel');
  private readonly placement = new PlacementAdmin();

  constructor(private readonly shell: AppShell) {}

  async mount(root: HTMLElement): Promise<void> {
    mountTabs(root, [
      { id: 'task-types', label: 'Task types', panel: this.taskPanel },
      { id: 'resources', label: 'Resources', panel: this.resourcePanel },
      { id: 'placement', label: 'Placement', panel: this.placementPanel },
      { id: 'infrastructure', label: 'Infrastructure', panel: this.infrastructurePanel },
    ]);
    await Promise.all([this.loadConfiguration(), this.loadInfrastructure(false), this.placement.mount(this.placementPanel)]);
  }

  private async loadConfiguration(): Promise<void> {
    this.taskPanel.replaceChildren(empty('Loading task type configuration...'));
    this.resourcePanel.replaceChildren(empty('Loading resource configuration...'));
    try {
      [this.config, this.catalog] = await Promise.all([adminApi.getConfiguration(), adminApi.getTaskCatalog()]);
      if (this.config.ignored_resource_keys.length) this.shell.notify(`Ignored obsolete resource keys: ${this.config.ignored_resource_keys.join(', ')}`);
      this.placement.setConfiguration(this.config);
      this.renderTaskTypes(); this.renderResources();
    } catch (error) {
      const message = (error as Error).message || 'Unable to load configuration.';
      this.taskPanel.replaceChildren(empty(message, true)); this.resourcePanel.replaceChildren(empty(message, true));
    }
  }

  private renderTaskTypes(): void {
    if (!this.config) return;
    this.taskPanel.replaceChildren();
    const search = element('input'); search.type = 'search'; search.placeholder = 'Name, identifier, category, runtime family';
    const state = element('select');
    [['all', 'All states'], ['enabled', 'Enabled'], ['disabled', 'Disabled']].forEach(([value, label]) => { const option = element('option'); option.value = value!; option.textContent = label!; state.append(option); });
    const count = text('span', '', 'admin-count');
    const list = element('div', 'config-type-list');
    const draw = (): void => {
      const query = search.value.trim().toLowerCase();
      const visible = this.config!.task_types.filter(config => {
        const catalogEntry = this.catalog?.task_types.find(entry => entry.name === config.tool);
        const stateMatches = state.value === 'all' || (config.enabled !== false) === (state.value === 'enabled');
        return stateMatches && (!query || [catalogEntry?.display_name, config.display_name, config.tool, catalogEntry?.category, config.category, config.runtime_family].filter(Boolean).join(' ').toLowerCase().includes(query));
      });
      count.textContent = `${visible.length} of ${this.config!.task_types.length} entries`;
      list.replaceChildren();
      if (!visible.length) list.append(empty('No task types match these filters.'));
      else visible.forEach(config => list.append(this.taskTypeRow(config)));
    };
    search.addEventListener('input', draw); state.addEventListener('change', draw);
    this.taskPanel.append(element('div', 'admin-toolbar', [element('label', 'admin-field', [text('span', 'Search'), search]), element('label', 'admin-field', [text('span', 'State'), state]), count]), list);
    draw();
  }

  private taskTypeRow(config: TaskTypeConfig): HTMLElement {
    const catalogEntry = this.catalog?.task_types.find(entry => entry.name === config.tool);
    const displayName = catalogEntry?.display_name || config.display_name;
    const category = catalogEntry?.category || config.category;
    const details = element('details', 'config-type-row');
    const summary = element('summary');
    const identity = element('div', '', [text('strong', displayName), text('code', config.tool), text('span', `${config.runtime_family} / ${category}`)]);
    const enabledLabel = element('label', 'admin-toggle');
    const enabled = element('input'); enabled.type = 'checkbox'; enabled.checked = config.enabled !== false; enabled.disabled = config.is_workflow_stage;
    enabledLabel.append(enabled, text('span', config.is_workflow_stage ? 'Workflow stage' : enabled.checked ? 'Enabled' : 'Disabled'));
    enabled.addEventListener('click', event => event.stopPropagation());
    enabled.addEventListener('change', async () => {
      try { await adminApi.updateConfiguration({ task_types: [{ tool: config.tool, enabled: enabled.checked } as TaskTypeConfig] }); this.shell.notify(`${displayName} ${enabled.checked ? 'enabled' : 'disabled'}.`, 'success'); await this.loadConfiguration(); }
      catch (error) { enabled.checked = !enabled.checked; this.shell.notify((error as Error).message, 'error'); }
    });
    summary.append(identity, enabledLabel); details.append(summary);

    if (config.resource_error) details.append(text('p', `Invalid: ${config.resource_error}`, 'error-state'));
    else if (config.effective_resources) {
      const values = Object.entries(config.effective_resources).filter(([, value]) => value !== null && value !== '').map(([key, value]) => `${key.replaceAll('_', ' ')}=${String(value)}`);
      details.append(text('p', values.join(', ') || 'Using global defaults', 'config-effective'));
    }
    const form = element('form', 'config-field-grid');
    const definitions = [...baseTaskFields, ...(this.config?.slurm.enabled ? slurmTaskFields.filter(field => field.key !== 'slurm_gres' || config.requires_gpu) : [])];
    const controls = new Map<FieldDefinition, HTMLInputElement | HTMLSelectElement>();
    definitions.forEach(definition => {
      const control = definition.type === 'boolean' ? element('select') : element('input');
      if (control instanceof HTMLSelectElement) {
        control.innerHTML = '<option value="">Inherit global policy</option><option value="true">Enabled</option><option value="false">Disabled</option>';
      } else {
        control.type = definition.type || 'text'; control.placeholder = definition.placeholder || '';
      }
      control.value = config[definition.key] === null || config[definition.key] === undefined ? '' : String(config[definition.key]);
      controls.set(definition, control); form.append(element('label', 'admin-field', [text('span', definition.label), control]));
    });
    const save = button('Save overrides', 'primary-button', 'submit'); form.append(save);
    form.addEventListener('submit', async event => {
      event.preventDefault(); setBusy(save, true, 'Saving...');
      const update: Record<string, ConfigValue> = { tool: config.tool };
      for (const [definition, control] of controls) {
        const value = fieldValue(config, definition, control);
        if (definition.key === 'max_runtime_seconds' && control.value.trim() && value === null) { this.shell.notify('Use a runtime such as 1:00:00 or 3600.', 'error'); setBusy(save, false); return; }
        update[definition.key] = value;
      }
      try { await adminApi.updateConfiguration({ task_types: [update as unknown as TaskTypeConfig] }); this.shell.notify(`${displayName} resource overrides saved.`, 'success'); await this.loadConfiguration(); }
      catch (error) { this.shell.notify((error as Error).message, 'error'); }
      finally { setBusy(save, false); }
    });
    details.append(form); return details;
  }

  private renderResources(): void {
    if (!this.config) return;
    this.resourcePanel.replaceChildren();
    const form = element('form', 'resource-form');
    const table = element('table', 'admin-table'); table.innerHTML = '<thead><tr><th>Parameter</th><th>Current value</th><th>Description</th></tr></thead>';
    const body = element('tbody'); const controls = new Map<string, HTMLInputElement>();
    globalFields.forEach(field => {
      const control = element('input'); control.value = this.config!.resources[field.key] === null || this.config!.resources[field.key] === undefined ? '' : String(this.config!.resources[field.key]);
      controls.set(field.key, control);
      body.append(element('tr', '', [text('td', field.label), element('td', '', [control]), text('td', field.description)]));
    });
    table.append(body);
    const slurmEnabled = element('input'); slurmEnabled.type = 'checkbox'; slurmEnabled.checked = this.config.slurm.enabled;
    const queues = element('input'); queues.value = this.config.slurm.allowed_queues.join(', '); queues.placeholder = 'gpu, cpu';
    const save = button('Save resource policy', 'primary-button', 'submit');
    form.append(element('div', 'admin-table-scroll', [table]), element('div', 'resource-policy-controls', [element('label', 'admin-check-field', [slurmEnabled, text('span', 'SLURM enabled')]), element('label', 'admin-field', [text('span', 'Allowed queues'), queues]), save]));
    form.addEventListener('submit', async event => {
      event.preventDefault(); setBusy(save, true, 'Saving...');
      const resources: Record<string, string> = {}; controls.forEach((control, key) => { resources[key] = control.value.trim(); });
      try {
        await adminApi.updateConfiguration({ resources, slurm: { enabled: slurmEnabled.checked, allowed_queues: queues.value.split(',').map(value => value.trim()).filter(Boolean) } });
        this.shell.notify('Resource policy saved.', 'success'); await this.loadConfiguration();
      } catch (error) { this.shell.notify((error as Error).message, 'error'); }
      finally { setBusy(save, false); }
    });
    this.resourcePanel.append(text('p', 'Global values apply when a task type has no override. Validation and persistence remain server-owned.', 'admin-section-copy'), form);
  }

  private async loadInfrastructure(force: boolean): Promise<void> {
    this.infrastructurePanel.replaceChildren(empty(force ? 'Refreshing infrastructure evidence...' : 'Loading infrastructure evidence...'));
    try {
      const data = force ? await adminApi.refreshInfrastructure() : await adminApi.getInfrastructure();
      this.infrastructurePanel.replaceChildren();
      const refresh = button('Refresh evidence'); refresh.addEventListener('click', () => void this.loadInfrastructure(true));
      this.infrastructurePanel.append(element('div', 'admin-section-heading', [element('div', '', [text('h2', 'Infrastructure readiness'), text('p', `${formatDate(data.checked_at)}${data.stale ? ', evidence is stale' : ''}`)]), refresh]));
      const summary = element('dl', 'infrastructure-summary');
      Object.entries(data.summary).forEach(([, item]) => summary.append(element('div', '', [text('dt', item.label), text('dd', item.status, `readiness-${item.status.toLowerCase()}`), ...(item.capacity ? [text('span', `Capacity ${item.capacity}`)] : []), ...(item.stale ? [text('b', 'Stale')] : [])])));
      this.infrastructurePanel.append(summary);
      if (!data.components?.length) { this.infrastructurePanel.append(empty('No component evidence is available.')); return; }
      const table = element('table', 'admin-table'); table.innerHTML = '<thead><tr><th>Component</th><th>State</th><th>Evidence</th><th>Checked</th><th>Failures</th><th>Next action</th></tr></thead>';
      const body = element('tbody'); data.components.forEach(component => body.append(element('tr', '', [text('td', component.component.replaceAll('_', ' ')), text('td', `${component.status}${component.stale ? ' / stale' : ''}`), text('td', `${component.reason_code}: ${component.message}`), text('td', formatDate(component.checked_at)), text('td', String(component.failure_count)), text('td', component.next_action || 'None')])));
      table.append(body); this.infrastructurePanel.append(element('div', 'admin-table-scroll', [table]));
    } catch (error) { this.infrastructurePanel.replaceChildren(empty((error as Error).message || 'Unable to load infrastructure evidence.', true)); }
  }
}
