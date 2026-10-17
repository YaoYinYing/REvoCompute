import type { InputFile, ParameterDefinition, TaskFormDefinition, WorkspaceCapability, WorkspaceStep, WorkspaceSummary, WorkspaceValues } from '../types';
import { authorizedFetch } from '../../../app/session';
import { parameterValue } from '../parameter-controls';
import { t } from '../../../app/i18n';
import { builtinPlugins } from './builtins';
import { inputByParameter } from './builtins';
import { PluginHost } from './PluginHost';
import type { WorkspaceContext } from './plugin-contract';
import { element, filePath } from './utils';

export interface InputWorkspaceOptions {
  onChange(): void;
  onError(message: string): void;
}

/**
 * One complete local form state: the raw files bound to each named role and the
 * parameter values as the controls hold them.
 *
 * A preset is what a demo load applies and what an undo restores, so the two are
 * the same operation with different contents rather than two mechanisms.
 */
export interface WorkspacePreset {
  files: Map<string, File[]>;
  parameters: Record<string, string>;
}

/** One value the application changed, described against the state it replaced. */
export interface PresetChange {
  label: string;
  before: string;
  after: string;
}

/** What one preset application actually put into the form. */
export interface PresetApplication {
  /** The form's own roles, in its own order, with the files the preset bound. */
  files: Array<{ role: string; title: string; names: string[] }>;
  /** The parameter values the preset itself declared, in the form's own order. */
  parameters: Array<{ name: string; label: string; value: string }>;
  /** Everything the application changed relative to the state it replaced. */
  changes: PresetChange[];
}

/**
 * The value a control holds when the form has not been touched: what the owning
 * parameter contract's own default projects to, which is exactly the state a
 * fresh control is rendered in.
 */
function defaultParameterValue(parameter: ParameterDefinition): string {
  if (parameter.type === 'bool') return String(parameter.defaultValue === true);
  return parameter.defaultValue == null ? '' : String(parameter.defaultValue);
}

/**
 * Write one parameter value into its live control.
 *
 * A `select` that does not offer the declared value gains the option rather than
 * silently discarding the assignment: a value the owning Task declares must be
 * visible in the form that is about to be submitted, not dropped between the
 * preset and the control. An empty value is never added as an option, because a
 * control reset to "no value" is a state, not a declared choice.
 */
function writeParameter(parameter: ParameterDefinition, control: HTMLInputElement | HTMLSelectElement, value: string): void {
  if (parameter.type === 'bool' && control instanceof HTMLInputElement) {
    control.checked = value === 'true';
    return;
  }
  if (value !== '' && control instanceof HTMLSelectElement && !Array.from(control.options).some(option => option.value === value)) {
    control.append(new Option(value, value));
  }
  control.value = value;
}

/**
 * Steps the protocol column renders. A step whose only capability is the
 * terminal `review` anchor is contract bookkeeping, not input the user works
 * with; it is dropped from the column (the Task Snapshot rail owns the visible
 * summary) while its capability stays in the submitted workspace. If a form ever
 * declares nothing but review, the step is kept so the anchor is still mounted.
 */
function displaySteps(steps: WorkspaceStep[]): WorkspaceStep[] {
  const visible = steps.filter(step => step.capabilities.some(capability => capability.plugin !== 'review'));
  return visible.length ? visible : steps;
}

export class InputWorkspace {
  private host = this.createHost();
  private context: WorkspaceContext | null = null;
  private mounted: TaskFormDefinition | null = null;
  private generation = 0;

  constructor(private readonly root: HTMLElement, private readonly options: InputWorkspaceOptions) {}

  private createHost(form?: TaskFormDefinition): PluginHost {
    return new PluginHost(builtinPlugins, { fetch: async (input, init) => {
      if (!form || typeof input !== 'string') throw new Error(t('ct.workspace.pluginScope'));
      const allowed = `/compute/api/types/${encodeURIComponent(form.name)}/workspace/normalize`;
      if (input !== allowed || init?.method?.toUpperCase() !== 'POST') throw new Error(t('ct.workspace.pluginScope'));
      return authorizedFetch(input, init);
    } });
  }

  async mount(form: TaskFormDefinition): Promise<void> {
    this.destroy(); const generation = this.generation; const host = this.createHost(form); this.host = host; this.root.replaceChildren();
    await host.load(form.input_workspace.plugins);
    if (generation !== this.generation || host !== this.host) { host.destroy(); return; }
    const displayed = new Set(displaySteps(form.input_workspace.steps));
    const stepTargets = new Map<string, HTMLElement>();
    form.input_workspace.steps.forEach(step => {
      if (!displayed.has(step)) {
        // Contract-only step (e.g. the terminal review anchor): keep it mounted so
        // its capability still contributes to collect(), but give it a detached
        // target so it never appears in the protocol column.
        stepTargets.set(step.id, element('div'));
        return;
      }
      const section = element('section', 'ct-protocol-step'); section.dataset.stepId = step.id;
      section.dataset.content = step.capabilities.every(capability => capability.plugin === 'parameters') ? 'parameters' : 'input';
      const heading = element('header', 'ct-step-heading');
      const identity = element('div'); const single = step.capabilities.length === 1;
      const input = single && step.capabilities[0]?.plugin === 'files';
      const parameters = single && step.capabilities[0]?.plugin === 'parameters';
      const title = parameters ? step.capabilities[0]!.title : step.title;
      const primaryRole = form.inputs.find(role => step.capabilities[0]?.options.roles instanceof Array && step.capabilities[0].options.roles.includes(role.id)) || form.inputs[0];
      identity.append(element('p', 'ct-section-kicker', step.capabilities.every(capability => capability.plugin === 'parameters') ? t('ct.param.heading') : t('ct.scientificInput')), element('h2', 'ct-step-title', input && primaryRole ? primaryRole.title : title));
      heading.append(identity);
      if (input && primaryRole) heading.append(element('span', 'ct-role-id', `role: ${primaryRole.id}`));
      if (step.description) heading.append(element('p', 'ct-step-description', step.description));
      const body = element('div', 'ct-step-body'); section.append(heading, body); this.root.append(section); stepTargets.set(step.id, body);
    });
    const definitions: WorkspaceCapability[] = form.input_workspace.steps.flatMap(step => step.capabilities.map(capability => ({ ...capability, stepId: step.id })));
    const roleFiles = new Map<string, File[]>(); const primaryIndexes = new Map<string, number>();
    let sequenceRole: string | null = null; let selections: Array<{ chain: string; residue: number }> = [];
    const context: WorkspaceContext = {
      form,
      roleFiles: role => [...(roleFiles.get(role) || [])],
      setRoleFiles: (role, files) => { roleFiles.set(role, files); if (!files[primaryIndexes.get(role) || 0]) primaryIndexes.set(role, 0); },
      primaryIndex: role => primaryIndexes.get(role) || 0,
      setPrimaryIndex: (role, index) => primaryIndexes.set(role, index),
      primaryFile: role => (roleFiles.get(role) || [])[primaryIndexes.get(role) || 0] || null,
      inputFiles: () => form.inputs.flatMap(role => {
        const files = roleFiles.get(role.id) || []; const primary = primaryIndexes.get(role.id) || 0;
        const ordered = primary === 0 ? files : [files[primary]!, ...files.filter((_, index) => index !== primary)];
        return ordered.map(file => ({ role: role.id, file }));
      }),
      structureFile: roleName => {
        const role = form.inputs.find(item => item.id === roleName) || form.inputs.find(item => item.type === 'protein_structure');
        return role ? context.primaryFile(role.id) : null;
      },
      setSequenceRole: role => { sequenceRole = role; }, sequenceRole: () => sequenceRole,
      sequence: () => '', sequenceName: () => '',
      parameters: () => Object.fromEntries(form.params.flatMap(parameter => {
        const input = document.querySelector<HTMLInputElement | HTMLSelectElement>(`[data-ct-parameter="${CSS.escape(parameter.name)}"]`);
        if (!input) return []; const value = input instanceof HTMLInputElement && input.type === 'checkbox' ? String(input.checked) : input.value;
        return value === '' ? [] : [[parameter.name, value]];
      })),
      structureSelections: () => [...selections], setStructureSelections: value => { selections = [...value]; },
      summaries: () => host.summaries(),
      changed: () => { this.refreshSnapshot(); this.options.onChange(); },
      filesChanged: () => { host.refresh(); this.options.onChange(); },
    };
    this.context = context;
    // The context serves one mount only; the form it was built for travels with
    // it, so a later preset application mutates the nodes this mount created and
    // never a control left over from the previous method.
    this.mounted = form;
    host.mount(definitions, context, definition => {
      const target = stepTargets.get(definition.stepId); if (!target) throw new Error(t('ct.workspace.missingStep', { step: definition.stepId }));
      const section = element('section', 'ct-workspace-component'); section.dataset.capabilityId = definition.id;
      if (form.input_workspace.steps.find(step => step.id === definition.stepId)!.capabilities.length > 1 && definition.title) section.append(element('h3', 'ct-component-title', definition.title));
      if (form.input_workspace.steps.find(step => step.id === definition.stepId)!.capabilities.length > 1 && definition.description) section.append(element('p', 'ct-component-description', definition.description));
      const body = element('div', 'ct-component-body'); section.append(body); target.append(section); return body;
    });
    host.refresh();
    // A declared capability whose plugin never mounted is a workspace failure. The
    // signal is the plugin id, not the localized message, so this holds under any locale.
    const unknown = host.unknownComponents();
    if (unknown.length) this.options.onError(unknown.map(item => item.message).join(' '));
  }

  private refreshSnapshot(): void { queueMicrotask(() => this.host.refresh()); }

  /** The form's state as a preset: every role's files and every parameter value. */
  snapshot(): WorkspacePreset {
    const files = new Map<string, File[]>();
    this.mounted?.inputs.forEach(role => files.set(role.id, this.context?.roleFiles(role.id) || []));
    const parameters: Record<string, string> = {};
    this.mounted?.params.forEach(parameter => {
      const control = inputByParameter(parameter.name);
      if (control) parameters[parameter.name] = parameterValue(parameter, control);
    });
    return { files, parameters };
  }

  /**
   * Whether the form holds anything a preset application would destroy: a bound
   * file, or a parameter a user moved off its own declared default.
   */
  isModified(): boolean {
    const current = this.snapshot();
    for (const files of current.files.values()) if (files.length) return true;
    return Boolean(this.mounted?.params.some(parameter => current.parameters[parameter.name] !== defaultParameterValue(parameter)));
  }

  /** Apply one preset to the live form and report exactly what changed. */
  apply(preset: WorkspacePreset): PresetApplication {
    const before = this.snapshot(); const form = this.mounted; const context = this.context;
    if (!form || !context) throw new Error(t('ct.workspace.pluginScope'));
    // A preset is a complete state, not a patch: the confirmation a reader
    // answers says their inputs are being *replaced*, so a role the preset does
    // not bind ends up empty and a parameter it does not declare returns to the
    // value a fresh control holds. Writing only the preset's own entries would
    // leave two examples' inputs combined in one form, or retain a file the
    // reader believes was replaced.
    const roles: PresetApplication['files'] = [];
    form.inputs.forEach(role => {
      const declared = preset.files.get(role.id) || [];
      context.setRoleFiles(role.id, [...declared]); context.setPrimaryIndex(role.id, 0);
      roles.push({ role: role.id, title: role.title, names: declared.map(filePath) });
    });
    const parameters: PresetApplication['parameters'] = [];
    form.params.forEach(parameter => {
      const control = inputByParameter(parameter.name); if (!control) return;
      writeParameter(parameter, control, preset.parameters[parameter.name] ?? defaultParameterValue(parameter));
      parameters.push({ name: parameter.name, label: parameter.label, value: parameterValue(parameter, control) });
    });
    const changes: PresetChange[] = [];
    roles.forEach(entry => {
      const previous = (before.files.get(entry.role) || []).map(filePath).join(', ');
      const next = entry.names.join(', ');
      if (previous !== next) changes.push({ label: entry.title, before: previous, after: next });
    });
    parameters.forEach(entry => {
      const previous = before.parameters[entry.name] ?? '';
      if (previous !== entry.value) changes.push({ label: entry.label, before: previous, after: entry.value });
    });
    // One edit, one change notification: the plugins and the form's own change
    // hook see the preset exactly as they would see the same values typed in.
    context.filesChanged();
    return { files: roles, parameters, changes };
  }

  /** Restore a preset and report what changed, exactly as applying one does. */
  restore(preset: WorkspacePreset): PresetApplication {
    return this.apply(preset);
  }
  inputFiles(): InputFile[] { return this.context?.inputFiles() || []; }
  sequence(): string { return this.context?.sequence() || ''; }
  sequenceName(): string { return this.context?.sequenceName() || ''; }
  sequenceRole(): string | null { return this.context?.sequenceRole() || null; }
  parameters(): Record<string, string> { return this.context?.parameters() || {}; }
  collect(): WorkspaceValues { return this.host.collect(); }
  summaries(): WorkspaceSummary[] { return this.context ? this.context.summaries() : []; }
  validate(): string[] { return this.host.validate(); }
  destroy(): void { this.generation++; this.host.destroy(); this.context = null; this.mounted = null; this.root.replaceChildren(); }
}
