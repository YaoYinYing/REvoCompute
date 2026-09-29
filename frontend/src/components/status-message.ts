export const showStatusMessage = (root: HTMLElement, message: string): void => {
  root.replaceChildren(document.createTextNode(message));
};
