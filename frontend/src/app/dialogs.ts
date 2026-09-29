import { createIcons, X } from 'lucide';

export interface DialogOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string | null;
  destructive?: boolean;
  content?: HTMLElement;
  initialFocus?: HTMLElement;
}

let activeClose: ((value: boolean) => void) | null = null;

function dialogElement(): HTMLDialogElement {
  const existing = document.querySelector<HTMLDialogElement>('#app-dialog');
  if (existing) return existing;
  const dialog = document.createElement('dialog');
  dialog.id = 'app-dialog';
  dialog.className = 'app-dialog';
  dialog.setAttribute('aria-labelledby', 'app-dialog-title');
  dialog.innerHTML = `
    <div class="app-dialog-frame">
      <header><h2 id="app-dialog-title"></h2><button class="icon-button" type="button" data-dialog-close aria-label="Close dialog"><i data-lucide="x"></i></button></header>
      <div class="app-dialog-body"></div>
      <footer class="app-dialog-actions"></footer>
    </div>`;
  document.body.append(dialog);
  createIcons({ icons: { X }, root: dialog });
  return dialog;
}

export function openDialog(options: DialogOptions): Promise<boolean> {
  activeClose?.(false);
  const invoker = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const dialog = dialogElement();
  const title = dialog.querySelector<HTMLElement>('#app-dialog-title')!;
  const body = dialog.querySelector<HTMLElement>('.app-dialog-body')!;
  const actions = dialog.querySelector<HTMLElement>('.app-dialog-actions')!;
  const close = dialog.querySelector<HTMLButtonElement>('[data-dialog-close]')!;
  title.textContent = options.title;
  body.replaceChildren();
  actions.replaceChildren();
  if (options.message) {
    const message = document.createElement('p');
    message.textContent = options.message;
    body.append(message);
  }
  if (options.content) body.append(options.content);
  close.hidden = options.cancelLabel === null;

  return new Promise(resolve => {
    let settled = false;
    const finish = (value: boolean): void => {
      if (settled) return;
      settled = true;
      activeClose = null;
      dialog.removeEventListener('cancel', cancel);
      if (dialog.open) dialog.close();
      invoker?.focus();
      resolve(value);
    };
    const cancel = (event: Event): void => {
      event.preventDefault();
      if (options.cancelLabel !== null) finish(false);
    };
    activeClose = finish;
    dialog.addEventListener('cancel', cancel);
    close.onclick = () => finish(false);

    if (options.cancelLabel !== null) {
      const cancelButton = document.createElement('button');
      cancelButton.type = 'button';
      cancelButton.className = 'secondary-button';
      cancelButton.textContent = options.cancelLabel || 'Cancel';
      cancelButton.addEventListener('click', () => finish(false));
      actions.append(cancelButton);
    }
    if (options.confirmLabel) {
      const confirmButton = document.createElement('button');
      confirmButton.type = 'button';
      confirmButton.className = options.destructive ? 'danger-button' : 'primary-button';
      confirmButton.textContent = options.confirmLabel;
      confirmButton.addEventListener('click', () => finish(true));
      actions.append(confirmButton);
    }
    dialog.showModal();
    (options.initialFocus || actions.querySelector<HTMLElement>('button') || close).focus();
  });
}

export const confirmAction = (options: Omit<DialogOptions, 'confirmLabel'> & { confirmLabel?: string }): Promise<boolean> =>
  openDialog({ cancelLabel: 'Cancel', confirmLabel: 'Confirm', destructive: true, ...options });

export const alertNotice = (title: string, message: string): Promise<boolean> =>
  openDialog({ title, message, cancelLabel: null, confirmLabel: 'Close' });
