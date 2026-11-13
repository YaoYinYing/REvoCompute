import type { components } from '../../api/schema.generated';
import { t } from '../../app/i18n';
import type { WorkspacePreset } from './input-workspace/InputWorkspace';

export type ClonePlan = components['schemas']['ClonePlanResponse'];
type CloneFinding = components['schemas']['CloneFinding'];
type CloneInputRole = components['schemas']['CloneInputRole'];

/**
 * The one preset a committed clone plan produces.
 *
 * Files are deliberately empty: Core has no submission-time input reference, so
 * every reused input is re-uploaded and hashed by the normal validation path.
 * The plan never carries file contents, a path, or a signed URL to turn into a
 * browser ``File``.
 */
export function clonePreset(plan: ClonePlan): WorkspacePreset {
  const parameters: Record<string, string> = {};
  plan.compatible_parameters.forEach(parameter => { parameters[parameter.name] = parameter.value; });
  return { files: new Map(), parameters };
}

function node<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text?: string): HTMLElementTagNameMap[K] {
  const value = document.createElement(tag);
  value.className = className;
  if (text != null) value.textContent = text;
  return value;
}

let headingSequence = 0;

/** One blocked parameter the reader must resolve before the draft can run. */
export interface CloneConflict {
  /** The owning parameter name; the control the reader edits. */
  name: string;
  label: string;
  message: string;
  /** The source's recorded value, as the control representation (may be empty). */
  recorded: string;
  /** The value the draft currently holds; keeping it is an explicit choice. */
  current: string;
}

export interface ClonePanelActions {
  /** Reset every control to the current schema's own defaults. */
  onReset?: () => void;
  /** Restore the form state that preceded the clone application. */
  onRevert?: () => void;
  /** Blocked parameters not yet resolved by the reader. */
  conflicts?: CloneConflict[];
  /** Parameters the reader changed after the preset was applied, with their current value. */
  edited?: Record<string, string>;
  /** Keep the value the form currently holds for one blocked parameter. */
  onKeepCurrent?: (name: string) => void;
}

/** A recorded value, with empty shown as an explicit value rather than absence. */
function shown(value: string | undefined): string | null {
  if (value === undefined) return null;
  return value === '' ? t('ct.clone.empty') : value;
}

function findings(items: CloneFinding[], className: string): HTMLElement | null {
  if (!items.length) return null;
  const list = node('ul', className);
  items.forEach(item => {
    const row = node('li');
    row.append(node('strong', '', item.field ? `${item.field}: ` : ''), document.createTextNode(item.message));
    // The server records a blocked value so the reader can compare it with the
    // current contract. ``0``, ``false`` and the empty string are values, not
    // absence, and must be shown along with the reason it was rejected.
    const recorded = shown(item.recorded_value);
    if (recorded !== null) row.append(node('small', 'ct-clone-recorded', t('ct.clone.recordedValue', { value: recorded })));
    list.append(row);
  });
  return list;
}

function conflicts(items: CloneConflict[], onKeepCurrent?: (name: string) => void): HTMLElement | null {
  if (!items.length) return null;
  const list = node('ul', 'ct-clone-conflicts');
  items.forEach(item => {
    const row = node('li');
    const recorded = shown(item.recorded) ?? t('ct.clone.empty');
    const current = shown(item.current) ?? t('ct.clone.empty');
    row.append(
      node('strong', '', item.label),
      node('p', 'ct-help', item.message),
      node('small', '', t('ct.clone.recordedValue', { value: recorded })),
      node('small', '', t('ct.clone.currentValue', { value: current })),
    );
    if (onKeepCurrent) {
      const keep = node('button', 'ct-secondary', t('ct.clone.keepCurrent', { value: current }));
      keep.type = 'button';
      keep.addEventListener('click', () => onKeepCurrent(item.name));
      row.append(keep);
    }
    list.append(row);
  });
  return list;
}

function inputRole(role: CloneInputRole): HTMLElement {
  const group = node('li');
  group.append(node('strong', '', role.title));
  if (!role.files.length) {
    group.append(node('p', 'ct-help', t('ct.clone.inputMissing')));
    return group;
  }
  const list = node('ul', 'ct-clone-files');
  role.files.forEach(file => {
    const reason = file.reason === 'not_owner' ? t('ct.clone.inputNotOwned')
      : file.reason === 'snapshot_unavailable' ? t('ct.clone.inputMissing')
        : t('ct.clone.inputUpload');
    list.append(node('li', '', `${file.original_name || role.role}${file.sha256 ? ` · sha256 ${file.sha256.slice(0, 12)}…` : ''} — ${reason}`));
  });
  group.append(list);
  return group;
}

/**
 * The visible, keyboard-reachable reconciliation panel for one clone.
 *
 * Every blocked value and every input that must be uploaded again is stated
 * individually; nothing here edits a field on its own. Reset and revert are
 * explicit reader actions, so a later edit is never overwritten by the panel.
 */
export function renderClonePanel(plan: ClonePlan, actions: ClonePanelActions = {}): HTMLElement {
  const panel = node('section', 'ct-clone');
  const heading = node('h2', '', t('ct.clone.heading'));
  heading.id = `ct-clone-heading-${++headingSequence}`;
  panel.setAttribute('aria-labelledby', heading.id);
  panel.append(heading, node('p', 'ct-help', t('ct.clone.intro', { id: plan.source_task_id })));

  const warnings = findings(plan.warnings, 'ct-clone-warnings');
  if (warnings) panel.append(node('p', 'ct-clone-label', t('ct.clone.warnings')), warnings);
  const blocked = findings(plan.blocked_fields, 'ct-clone-blocked');
  if (blocked) panel.append(node('p', 'ct-clone-label', t('ct.clone.blocked')), blocked);

  const unresolved = conflicts(actions.conflicts ?? [], actions.onKeepCurrent);
  if (unresolved) {
    panel.append(
      node('p', 'ct-clone-label', t('ct.clone.conflicts')),
      node('p', 'ct-help', t('ct.clone.conflictHelp')),
      unresolved,
    );
  }

  if (plan.compatible_parameters.length) {
    const edited = actions.edited ?? {};
    const list = node('ul', 'ct-clone-parameters');
    plan.compatible_parameters.forEach(parameter => {
      const changed = Object.prototype.hasOwnProperty.call(edited, parameter.name);
      const value = changed ? edited[parameter.name]! : parameter.value;
      const row = node('li');
      row.append(
        node('span', '', parameter.name),
        node('strong', '', value === '' ? t('ct.clone.empty') : value),
        // A value the reader changed is no longer the plan's: the panel must not
        // keep claiming the source is what this draft will submit.
        node('small', '', changed
          ? t('ct.clone.edited')
          : parameter.source === 'recorded' ? t('ct.clone.recorded') : t('ct.clone.defaulted')),
      );
      list.append(row);
    });
    panel.append(node('p', 'ct-clone-label', t('ct.clone.parameters')), list);
  }

  const roles = plan.reusable_inputs.filter(role => role.files.length || role.required);
  if (roles.length) {
    const list = node('ul', 'ct-clone-inputs');
    roles.forEach(role => list.append(inputRole(role)));
    panel.append(node('p', 'ct-clone-label', t('ct.clone.inputs')), list);
  }

  if (actions.onReset || actions.onRevert) {
    const controls = node('div', 'ct-actions');
    if (actions.onReset) {
      const reset = node('button', 'ct-secondary', t('ct.clone.reset')); reset.type = 'button';
      reset.addEventListener('click', actions.onReset); controls.append(reset);
    }
    if (actions.onRevert) {
      const revert = node('button', 'ct-secondary', t('ct.clone.undo')); revert.type = 'button';
      revert.addEventListener('click', actions.onRevert); controls.append(revert);
    }
    panel.append(controls);
  }
  return panel;
}
