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

export interface ClonePanelActions {
  /** Reset every control to the current schema's own defaults. */
  onReset?: () => void;
  /** Restore the form state that preceded the clone application. */
  onRevert?: () => void;
}

function findings(items: CloneFinding[], className: string): HTMLElement | null {
  if (!items.length) return null;
  const list = node('ul', className);
  items.forEach(item => {
    const row = node('li');
    row.append(node('strong', '', item.field ? `${item.field}: ` : ''), document.createTextNode(item.message));
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

  if (plan.compatible_parameters.length) {
    const list = node('ul', 'ct-clone-parameters');
    plan.compatible_parameters.forEach(parameter => {
      const row = node('li');
      row.append(
        node('span', '', parameter.name),
        node('strong', '', parameter.value === '' ? t('ct.clone.empty') : parameter.value),
        node('small', '', parameter.source === 'recorded' ? t('ct.clone.recorded') : t('ct.clone.defaulted')),
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
