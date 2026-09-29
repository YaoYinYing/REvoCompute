export type Child = Node | string | null | undefined | false;

export function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  children: Child[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  for (const child of children) {
    if (child instanceof Node) node.append(child);
    else if (typeof child === 'string') node.append(document.createTextNode(child));
  }
  return node;
}

export function text(tag: keyof HTMLElementTagNameMap, value: string, className?: string): HTMLElement {
  const node = element(tag, className);
  node.textContent = value;
  return node;
}

export function button(label: string, className = 'secondary-button', type: 'button' | 'submit' = 'button'): HTMLButtonElement {
  const node = element('button', className);
  node.type = type;
  node.textContent = label;
  return node;
}

export function empty(message: string, error = false): HTMLElement {
  return text('p', message, `admin-empty${error ? ' error-state' : ''}`);
}

export function formatDate(value?: number | string | null): string {
  if (value === null || value === undefined || value === '') return 'Not recorded';
  const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleString();
}

export function formatCredits(value: number, signed = false): string {
  const rendered = Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
  return signed && value > 0 ? `+${rendered}` : rendered;
}

export function formatBytes(bytes: number): string {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
  return `${value.toFixed(unit > 0 && value < 10 ? 1 : 0)} ${units[unit]}`;
}

export interface DialogOptions<T> {
  title: string;
  content: HTMLElement;
  confirmLabel?: string;
  destructive?: boolean;
  readValue?: () => T;
  validate?: (value: T) => string | null;
}

export function openDialog<T = boolean>(options: DialogOptions<T>): Promise<T | null> {
  return new Promise(resolve => {
    const dialog = element('dialog', 'admin-dialog');
    const headingId = `admin-dialog-title-${globalThis.crypto?.randomUUID?.() ?? Date.now().toString(36)}`;
    dialog.setAttribute('aria-labelledby', headingId);
    const form = element('form', 'admin-dialog-form');
    form.method = 'dialog';
    const heading = text('h2', options.title); heading.id = headingId;
    const header = element('header', 'admin-dialog-header', [heading]);
    const message = element('p', 'admin-dialog-error');
    message.setAttribute('role', 'alert');
    const actions = element('footer', 'admin-dialog-actions');
    const cancel = button(options.confirmLabel ? 'Cancel' : 'Close');
    cancel.value = 'cancel';
    cancel.addEventListener('click', () => dialog.close('cancel'));
    const confirm = options.confirmLabel ? button(options.confirmLabel, options.destructive ? 'admin-danger-button' : 'primary-button', 'submit') : null;
    if (confirm) confirm.value = 'confirm';
    actions.append(cancel);
    if (confirm) actions.append(confirm);
    form.append(header, options.content, message, actions);
    dialog.append(form);
    document.body.append(dialog);

    let result: T | null = null;
    form.addEventListener('submit', event => {
      const submitter = (event as SubmitEvent).submitter as HTMLButtonElement | null;
      if (submitter?.value !== 'confirm') return;
      const value = options.readValue ? options.readValue() : true as T;
      const validation = options.validate?.(value);
      if (validation) {
        event.preventDefault();
        message.textContent = validation;
        return;
      }
      result = value;
    });
    dialog.addEventListener('close', () => { dialog.remove(); resolve(result); }, { once: true });
    dialog.addEventListener('cancel', () => { result = null; });
    dialog.showModal();
  });
}

export function reasonContent(message: string, confirmation?: string): { root: HTMLElement; reason: HTMLTextAreaElement; confirmation?: HTMLInputElement } {
  const root = element('div', 'admin-dialog-fields');
  root.append(text('p', message, 'admin-dialog-copy'));
  const reasonLabel = element('label', 'admin-field', [text('span', 'Reason')]);
  const reason = element('textarea');
  reason.rows = 3;
  reason.maxLength = 1000;
  reason.required = true;
  reasonLabel.append(reason);
  root.append(reasonLabel);
  if (!confirmation) return { root, reason };
  const confirmationLabel = element('label', 'admin-field', [text('span', `Type ${confirmation} to confirm`)]);
  const confirmationInput = element('input');
  confirmationInput.type = 'text';
  confirmationInput.autocomplete = 'off';
  confirmationLabel.append(confirmationInput);
  root.append(confirmationLabel);
  return { root, reason, confirmation: confirmationInput };
}

export function setBusy(control: HTMLButtonElement, busy: boolean, busyLabel = 'Working...'): void {
  if (busy) control.dataset.label = control.textContent || '';
  control.disabled = busy;
  control.textContent = busy ? busyLabel : control.dataset.label || control.textContent;
}
