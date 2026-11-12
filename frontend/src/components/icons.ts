import { createIcons, Download, Expand, FolderOpen, Link, Minimize, RefreshCw } from 'lucide';

const resultIcons = { Download, Expand, FolderOpen, Link, Minimize, RefreshCw };

export type ResultIcon = keyof typeof resultIcons;

export const setButtonIcon = (button: HTMLButtonElement | HTMLAnchorElement, icon: ResultIcon): void => {
  const placeholder = document.createElement('i');
  placeholder.dataset.lucide = icon.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`).replace(/^-/, '');
  button.replaceChildren(placeholder);
  createIcons({
    attrs: {
      'aria-hidden': 'true',
      width: 18,
      height: 18,
      'stroke-width': 1.8,
    },
    icons: resultIcons,
    root: button,
  });
};
