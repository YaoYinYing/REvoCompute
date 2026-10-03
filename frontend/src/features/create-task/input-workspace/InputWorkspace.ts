import type { InputFile, TaskFormDefinition, WorkspaceCapability, WorkspaceSummary, WorkspaceValues } from '../types';
import { authorizedFetch } from '../../../app/session';
import { builtinPlugins } from './builtins';
import { PluginHost } from './PluginHost';
import type { WorkspaceContext } from './plugin-contract';
import { element } from './utils';

export interface InputWorkspaceOptions {
  onChange(): void;
  onError(message: string): void;
}

export class InputWorkspace {
  private host = this.createHost();
  private context: WorkspaceContext | null = null;
  private generation = 0;

  constructor(private readonly root: HTMLElement, private readonly options: InputWorkspaceOptions) {}

  private createHost(form?: TaskFormDefinition): PluginHost {
    return new PluginHost(builtinPlugins, { fetch: async (input, init) => {
      if (!form || typeof input !== 'string') throw new Error('Workspace plugin request is outside its declared API scope.');
      const allowed = `/compute/api/types/${encodeURIComponent(form.name)}/workspace/normalize`;
      if (input !== allowed || init?.method?.toUpperCase() !== 'POST') throw new Error('Workspace plugin request is outside its declared API scope.');
      return authorizedFetch(input, init);
    } });
  }

  async mount(form: TaskFormDefinition): Promise<void> {
    this.destroy(); const generation = this.generation; const host = this.createHost(form); this.host = host; this.root.replaceChildren();
    await host.load(form.input_workspace.plugins);
    if (generation !== this.generation || host !== this.host) { host.destroy(); return; }
    const stepTargets = new Map<string, HTMLElement>();
    form.input_workspace.steps.forEach((step, index) => {
      const section = element('section', 'ct-protocol-step'); section.dataset.stepId = step.id;
      const heading = element('header', 'ct-step-heading'); heading.append(element('span', 'ct-step-number', String(index + 1).padStart(2, '0')), element('h2', 'ct-step-title', step.title));
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
      changed: () => { this.refreshReview(); this.options.onChange(); },
      filesChanged: () => { host.refresh(); this.options.onChange(); },
    };
    this.context = context;
    host.mount(definitions, context, definition => {
      const target = stepTargets.get(definition.stepId); if (!target) throw new Error(`Missing workspace step: ${definition.stepId}`);
      const section = element('section', 'ct-workspace-component'); section.dataset.capabilityId = definition.id;
      if (definition.title) section.append(element('h3', 'ct-component-title', definition.title));
      if (definition.description) section.append(element('p', 'ct-component-description', definition.description));
      const body = element('div', 'ct-component-body'); section.append(body); target.append(section); return body;
    });
    host.refresh();
    const errors = host.validate().filter(error => error.includes('unsupported component'));
    if (errors.length) this.options.onError(errors.join(' '));
  }

  private refreshReview(): void { queueMicrotask(() => this.host.refresh()); }
  inputFiles(): InputFile[] { return this.context?.inputFiles() || []; }
  sequence(): string { return this.context?.sequence() || ''; }
  sequenceName(): string { return this.context?.sequenceName() || ''; }
  sequenceRole(): string | null { return this.context?.sequenceRole() || null; }
  parameters(): Record<string, string> { return this.context?.parameters() || {}; }
  collect(): WorkspaceValues { return this.host.collect(); }
  summaries(): WorkspaceSummary[] { return this.context ? this.context.summaries() : []; }
  validate(): string[] { return this.host.validate(); }
  destroy(): void { this.generation++; this.host.destroy(); this.context = null; this.root.replaceChildren(); }
}
