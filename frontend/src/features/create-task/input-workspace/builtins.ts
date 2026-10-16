import { createIcons, Dice5 } from 'lucide';
import { parameterValue, seedConstant, validateParameter } from '../parameter-controls';
import type { ParameterDefinition } from '../types';
import { t } from '../../../app/i18n';
import type { WorkspaceContext, WorkspacePlugin, WorkspacePluginInstance } from './plugin-contract';
import { element, filePath, formatBytes, matchesExtension, parseSequence } from './utils';

function inputByParameter(name: string): HTMLInputElement | HTMLSelectElement | null {
  return document.querySelector(`[data-ct-parameter="${CSS.escape(name)}"]`);
}

function renderParameter(parameter: ParameterDefinition, context: WorkspaceContext): HTMLElement {
  const field = element('div', 'ct-parameter');
  const heading = element('div', 'ct-parameter-heading');
  const label = element('label', 'ct-label', parameter.unit ? `${parameter.label} (${parameter.unit})` : parameter.label);
  const id = `ct-param-${parameter.name}`; label.htmlFor = id; heading.append(label);
  if (parameter.defaultValue != null) {
    const reset = element('button', 'ct-reset', t('ct.param.reset')); reset.type = 'button';
    reset.addEventListener('click', () => {
      if (control instanceof HTMLInputElement && control.type === 'checkbox') control.checked = parameter.defaultValue === true;
      else control.value = parameter.defaultValue == null ? '' : String(parameter.defaultValue);
      control.dispatchEvent(new Event('input', { bubbles: true }));
    });
    heading.append(reset);
  }
  field.append(heading);
  let control: HTMLInputElement | HTMLSelectElement;
  if (parameter.type === 'bool') {
    control = element('input', 'ct-checkbox'); control.type = 'checkbox'; control.checked = parameter.defaultValue === true;
  } else if (parameter.choices.length && parameter.choices.length <= 20) {
    const select = element('select', 'ct-control');
    if (!parameter.required && parameter.defaultValue == null) select.append(new Option(t('ct.param.useDefault'), ''));
    parameter.choices.forEach(choice => select.append(new Option(String(choice), String(choice), false, String(choice) === String(parameter.defaultValue ?? ''))));
    control = select;
  } else {
    const input = element('input', 'ct-control');
    // A declared ``format: date`` is drawn as the browser's own calendar-date
    // control rather than a bare text field, so the published date contract is
    // the one the user edits.
    input.type = parameter.type === 'int' || parameter.type === 'float' ? 'number' : parameter.dateFormat ? 'date' : 'text';
    input.value = parameter.defaultValue == null ? '' : String(parameter.defaultValue);
    input.required = parameter.required;
    // The spinner hint projects the server's own range: an inclusive bound is
    // used directly, and a side that declares only an exclusive bound seeds the
    // hint from it. The hint steers the spinner; the gate is the validator.
    if (parameter.minimum != null) input.min = String(parameter.minimum);
    else if (parameter.exclusiveMinimum != null) input.min = String(parameter.exclusiveMinimum);
    if (parameter.maximum != null) input.max = String(parameter.maximum);
    else if (parameter.exclusiveMaximum != null) input.max = String(parameter.exclusiveMaximum);
    if (parameter.step != null) input.step = String(parameter.step); else if (parameter.type === 'float') input.step = 'any';
    if (parameter.choices.length) {
      const list = element('datalist'); list.id = `${id}-choices`;
      parameter.choices.forEach(choice => list.append(new Option(String(choice), String(choice))));
      input.setAttribute('list', list.id); field.append(list);
    }
    control = input;
  }
  control.id = id; control.dataset.ctParameter = parameter.name;
  const error = element('p', 'ct-field-error'); error.hidden = true; error.id = `${id}-error`;
  control.setAttribute('aria-describedby', error.id);
  const changed = () => { control.removeAttribute('aria-invalid'); error.hidden = true; context.changed(); };
  control.addEventListener('input', changed); control.addEventListener('change', changed); if (parameter.seed && control instanceof HTMLInputElement && control.type === 'number') field.append(seedControl(parameter, control)); else field.append(control);
  if (parameter.description) field.append(element('p', 'ct-help', parameter.description));
  if (parameter.help) { const details = element('details', 'ct-more-help'); details.append(element('summary', '', t('ct.param.why')), element('p', '', parameter.help)); field.append(details); }
  field.append(error); return field;
}

/**
 * The seed field's own control: one editable value, a dice button inside it.
 *
 * The value stays a normal number input - the same element the form already
 * collects from - so drawing a seed is an ordinary edit. The dice is the
 * field's only extra affordance; it reads one uniform integer from the task's
 * declared generation domain and reports it through the control's own `input`
 * event, so validation, the Task Snapshot, and submission all see one edit.
 */
function seedControl(parameter: ParameterDefinition, control: HTMLInputElement): HTMLElement {
  const wrap = element('div', 'ct-seed-field');
  const dice = element('button', 'ct-seed'); dice.type = 'button';
  dice.setAttribute('aria-label', t('ct.param.randomize', { label: parameter.label }));
  dice.append(element('i')); dice.firstElementChild!.setAttribute('data-lucide', 'dice-5');
  dice.addEventListener('click', () => {
    control.value = String(seedConstant(parameter, draw => crypto.getRandomValues(draw)));
    control.removeAttribute('aria-invalid');
    control.dispatchEvent(new Event('input', { bubbles: true }));
  });
  wrap.append(control, dice); createIcons({ icons: { Dice5 }, root: wrap });
  return wrap;
}

function validateParameters(parameters: ParameterDefinition[]): string[] {
  const errors: string[] = [];
  parameters.forEach(parameter => {
    const control = inputByParameter(parameter.name); if (!control) return;
    const error = validateParameter(parameter, control);
    const message = document.getElementById(`${control.id}-error`);
    control.toggleAttribute('aria-invalid', Boolean(error));
    if (message) { message.textContent = error || ''; message.hidden = !error; }
    if (error) errors.push(error);
  });
  return errors;
}

const filesPlugin: WorkspacePlugin = {
  id: 'files',
  mount(target, definition, context) {
    const controls: Array<{ role: TaskFormRole; input: HTMLInputElement; list: HTMLElement; error: HTMLElement }> = [];
    const requestedRoles = Array.isArray(definition.options.roles) ? definition.options.roles.filter(value => typeof value === 'string') : [];
    const roles = requestedRoles.length ? context.form.inputs.filter(role => requestedRoles.includes(role.id)) : context.form.inputs;
    const primaryRole = typeof definition.options.primary_role === 'string' ? definition.options.primary_role : roles.find(role => role.cardinality.max > 1)?.id;
    roles.forEach(role => {
      const group = element('div', 'ct-file-role');
      const label = element('label', 'ct-label', role.title); const id = `ct-files-${definition.id}-${role.id}`; label.htmlFor = id;
      const input = element('input'); input.id = id; input.type = 'file'; input.multiple = role.cardinality.max > 1; input.accept = role.accept || role.extensions.join(',');
      const hint = element('p', 'ct-help', role.description || t('ct.files.hint', { minimum: role.cardinality.min, maximum: role.cardinality.max, formats: role.formats.join(', ') }));
      const list = element('div', 'ct-file-list');
      const preview = element('div', 'ct-input-preview'); preview.hidden = true; preview.setAttribute('aria-label', t('ct.files.preview'));
      let previewGeneration = 0;
      const error = element('p', 'ct-field-error'); error.hidden = true; input.setAttribute('aria-describedby', `${id}-error`); error.id = `${id}-error`;
      const render = () => {
        const files = context.roleFiles(role.id); list.replaceChildren();
        const generation = ++previewGeneration; preview.hidden = true; preview.textContent = '';
        const first = files[0];
        // A bounded view of the original bytes; no normalization or scientific interpretation.
        if (first && /\.(?:a3m|aln|fasta|fa|faa|txt|csv|tsv)$/i.test(first.name)) {
          void first.slice(0, 65536).text().then(source => {
            if (generation !== previewGeneration || !target.isConnected) return;
            preview.replaceChildren();
            preview.append(element('p', 'ct-preview-caption', t('ct.files.preview')));
            if (role.type === 'alignment' && source.startsWith('>')) {
              const records = source.split(/^>/m).filter(Boolean).slice(0, 8);
              const rows = element('div', 'ct-alignment-rows'); rows.tabIndex = 0;
              for (const record of records) { const lines = record.split(/\r?\n/); const name = lines.shift() || ''; const row = element('div', 'ct-alignment-row'); const label = element('span', '', name.split(/\s+/)[0]); label.title = name; const sequence = element('code', '', lines.join('')); row.append(label, sequence); rows.append(row); }
              preview.append(rows, element('p', 'ct-preview-foot', t('ct.files.previewOriginal')));
            } else { preview.append(element('pre', '', source.split(/\r?\n/).slice(0, 12).join('\n'))); }
            preview.hidden = false;
          }).catch(() => { /* Upload remains available when a local preview cannot be read. */ });
        }
        if (!files.length) list.textContent = t('ct.files.none');
        files.forEach((file, index) => {
          const row = element('div', 'ct-file-row');
          const name = element('span', '', `${filePath(file)} (${formatBytes(file.size)})`); row.append(name);
          if (primaryRole === role.id && files.length > 1) {
            const radio = element('input'); radio.type = 'radio'; radio.name = `ct-primary-${role.id}`; radio.checked = context.primaryIndex(role.id) === index;
            radio.setAttribute('aria-label', t('ct.files.usePrimary', { name: file.name })); radio.addEventListener('change', () => { context.setPrimaryIndex(role.id, index); context.changed(); }); row.append(radio);
          }
          list.append(row);
        });
      };
      input.addEventListener('change', () => { context.setRoleFiles(role.id, Array.from(input.files || [])); render(); context.filesChanged(); });
      const contract = element('details', 'ct-input-contract'); contract.append(element('summary', '', t('ct.files.contract')), hint); if (roles.length === 1) label.classList.add('sr-only'); group.append(label, input, list, preview, contract, error); target.append(group); controls.push({ role, input, list, error });
    });
    return {
      readValue: () => Object.fromEntries(roles.map(role => [role.id, context.roleFiles(role.id).map(filePath)])),
      summarize: () => {
        const files = context.inputFiles(); if (!files.length) return null;
        const [first] = files; if (!first) return null;
        const extra = files.length > 1 ? t('ct.summary.more', { count: files.length - 1 }) : '';
        return { label: t('ct.summary.input'), value: `${first.role}: ${filePath(first.file)}${extra}` };
      },
      validate: () => {
        const errors: string[] = [];
        controls.forEach(({ role, input, error }) => {
          const files = context.roleFiles(role.id); const sequence = context.sequenceRole() === role.id && context.sequence() ? 1 : 0;
          const roleErrors: string[] = [];
          const range = { role: role.title, minimum: role.cardinality.min, maximum: role.cardinality.max };
          if (files.length + sequence < role.cardinality.min || files.length + sequence > role.cardinality.max) roleErrors.push(t('ct.files.range', range));
          if (files.some(file => !matchesExtension(file, role.extensions))) roleErrors.push(t('ct.files.format', range));
          input.toggleAttribute('aria-invalid', roleErrors.length > 0); error.textContent = roleErrors[0] || ''; error.hidden = !roleErrors.length; errors.push(...roleErrors);
        });
        const bytes = context.inputFiles().reduce((sum, item) => sum + item.file.size, 0) + new Blob([context.sequence()]).size;
        if (bytes > context.form.max_request_bytes) errors.push(t('ct.files.tooLarge', { limit: formatBytes(context.form.max_request_bytes) }));
        return errors;
      },
    };
  },
};

type TaskFormRole = WorkspaceContext['form']['inputs'][number];

const sequencePlugin: WorkspacePlugin = {
  id: 'sequence',
  mount(target, definition, context) {
    const role = typeof definition.options.role === 'string' ? definition.options.role : '';
    if (!context.form.inputs.some(item => item.id === role)) throw new Error(t('ct.sequence.roleInvalid'));
    context.setSequenceRole(role);
    const name = element('input', 'ct-control'); name.placeholder = t('ct.sequence.name'); name.setAttribute('aria-label', t('ct.sequence.name'));
    const textarea = element('textarea', 'ct-sequence'); textarea.placeholder = t('ct.sequence.placeholder'); textarea.setAttribute('aria-label', t('ct.sequence.label'));
    const preview = element('pre', 'ct-sequence-preview', t('ct.sequence.empty')); const error = element('p', 'ct-field-error'); error.hidden = true;
    const refresh = () => { const parsed = parseSequence(textarea.value); if (parsed.name && !name.value) name.value = parsed.name; preview.textContent = parsed.sequence ? `${parsed.sequence.match(/.{1,10}/g)?.join(' ')}\n${t('ct.sequence.residues', { count: parsed.sequence.length })}` : t('ct.sequence.empty'); error.textContent = parsed.error; error.hidden = !parsed.error; context.changed(); };
    textarea.addEventListener('input', refresh); name.addEventListener('input', () => context.changed()); target.append(name, textarea, preview, error);
    Object.defineProperties(context, { sequence: { value: () => parseSequence(textarea.value).sequence }, sequenceName: { value: () => name.value.trim() } });
    return {
      readValue: () => ({ name: name.value.trim(), sequence: context.sequence() }),
      summarize: () => context.sequence() ? { label: t('ct.summary.sequence'), value: t('ct.sequence.residues', { count: context.sequence().length }) } : null,
      validate: () => {
        const parsed = parseSequence(textarea.value); const errors = parsed.error ? [parsed.error] : [];
        if (parsed.sequence && context.roleFiles(role).length) errors.push(t('ct.sequence.conflict', { role }));
        textarea.toggleAttribute('aria-invalid', errors.length > 0); error.textContent = errors[0] || ''; error.hidden = !errors.length; return errors;
      },
    };
  },
};

const structurePlugin: WorkspacePlugin = {
  id: 'structure',
  mount(target, definition, context) {
    const selectable = definition.options.select_chains === true || definition.options.select_residues === true;
    const prompt = t('ct.structure.prompt');
    const status = element('p', 'ct-help', prompt);
    const host = element('div', 'ct-structure-viewer'); host.hidden = true; target.append(status, host);
    let generation = 0; let viewer: Awaited<ReturnType<(typeof import('../../structure/MolecularViewer'))['MolecularViewer']['mount']>> | null = null; let removeListener: (() => void) | null = null;
    let selectedFile: File | null = null; let queue = Promise.resolve();
    const render = async (current: number, file: File | null) => {
      if (generation !== current) return;
      context.setStructureSelections([]);
      if (!file || !matchesExtension(file, ['.pdb', '.cif', '.mmcif'])) { host.hidden = true; status.textContent = prompt; await viewer?.clear(); return; }
      status.textContent = t('ct.structure.reading', { name: filePath(file) });
      try {
        const data = await file.text(); if (generation !== current) return;
        if (!viewer) {
          const { MolecularViewer } = await import('../../structure/MolecularViewer');
          if (generation !== current) return;
          const mounted = await MolecularViewer.mount(host, { selectionEnabled: selectable, showControls: selectable });
          if (generation !== current) { mounted.dispose(); return; }
          viewer = mounted;
          if (selectable) removeListener = mounted.onSelectionChanged(residues => { context.setStructureSelections(residues); context.changed(); });
        }
        await viewer.loadStructure({ data, format: file.name.toLowerCase().endsWith('.pdb') ? 'pdb' : 'mmcif', label: filePath(file) });
        if (generation !== current) return; host.hidden = false; status.textContent = selectable ? t('ct.structure.selectResidues', { name: filePath(file) }) : t('ct.structure.inspection', { name: filePath(file) });
      } catch { if (generation === current) { host.hidden = true; status.textContent = t('ct.structure.failed'); } }
    };
    const refresh = (): Promise<void> => {
      const role = typeof definition.options.role === 'string' ? definition.options.role : undefined; const file = context.structureFile(role);
      if (file === selectedFile) return queue;
      selectedFile = file; const current = ++generation;
      queue = queue.catch(() => undefined).then(() => render(current, file));
      return queue;
    };
    return { refresh, readValue: () => ({ selected_residues: context.structureSelections() }), summarize: () => context.structureSelections().length ? { label: t('ct.summary.selection'), value: t('ct.sequence.residues', { count: context.structureSelections().length }) } : null, destroy: () => { generation++; selectedFile = null; removeListener?.(); removeListener = null; viewer?.dispose(); viewer = null; } };
  },
};

function parameterPlugin(id: 'regions' | 'parameters'): WorkspacePlugin {
  return { id, mount(target, definition, context) {
    const fields = Array.isArray(definition.options.fields) ? definition.options.fields : [];
    const params = context.form.params.filter(parameter => id === 'regions' ? fields.includes(parameter.name) : !fieldsInWorkspace(context.form).has(parameter.name));
    const basic = params.filter(parameter => !parameter.advanced); const advanced = params.filter(parameter => parameter.advanced);
    const render = (items: ParameterDefinition[], parent: HTMLElement) => items.forEach(parameter => parent.append(renderParameter(parameter, context)));
    if (basic.length) { const grid = element('div', 'ct-parameter-grid'); render(basic, grid); target.append(grid); }
    if (advanced.length) { const details = element('details', 'ct-advanced'); details.append(element('summary', '', t('ct.param.advanced', { count: advanced.length }))); const grid = element('div', 'ct-parameter-grid'); render(advanced, grid); details.append(grid); target.append(details); }
    if (!params.length) target.append(element('p', 'ct-help', t('ct.param.none')));
    return {
      readValue: () => Object.fromEntries(params.flatMap(parameter => { const control = inputByParameter(parameter.name); return control ? [[parameter.name, parameterValue(parameter, control)]] : []; })),
      summarize: () => params.flatMap(parameter => { const control = inputByParameter(parameter.name); if (!control) return []; const value = parameterValue(parameter, control); return String(value) === String(parameter.defaultValue ?? '') ? [] : [{ label: parameter.label, value: `${value}${parameter.unit ? ` ${parameter.unit}` : ''}` }]; }),
      validate: () => validateParameters(params),
    };
  } };
}

function fieldsInWorkspace(form: WorkspaceContext['form']): Set<string> {
  return new Set(form.input_workspace.steps.flatMap(step => step.capabilities.flatMap(capability => Array.isArray(capability.options.fields) ? capability.options.fields.filter((field): field is string => typeof field === 'string') : [])));
}

const reviewPlugin: WorkspacePlugin = {
  // The `review` capability is the task contract's terminal anchor. It renders
  // nothing: the Task Snapshot rail is the single visible submission summary, and
  // the protocol column shows only input capabilities. It still owns the
  // submission payload fields the server contract expects from the terminal step.
  id: 'review', mount(_target, _definition, context): WorkspacePluginInstance {
    return { readValue: () => ({ task_type: context.form.name, inputs: context.inputFiles().map(item => ({ role: item.role, path: filePath(item.file) })), params: context.parameters() }) };
  },
};

export const builtinPlugins: WorkspacePlugin[] = [filesPlugin, sequencePlugin, structurePlugin, parameterPlugin('regions'), parameterPlugin('parameters'), reviewPlugin];
