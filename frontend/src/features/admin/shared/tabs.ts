import { element } from './dom';

export interface TabDefinition {
  id: string;
  label: string;
  panel: HTMLElement;
}

export function mountTabs(root: HTMLElement, definitions: TabDefinition[], initial = definitions[0]?.id): void {
  const list = element('div', 'admin-tabs');
  list.setAttribute('role', 'tablist');
  const activate = (id: string): void => {
    definitions.forEach(definition => {
      const selected = definition.id === id;
      definition.panel.hidden = !selected;
      definition.panel.setAttribute('role', 'tabpanel');
      const tab = list.querySelector<HTMLButtonElement>(`[data-tab="${definition.id}"]`);
      tab?.setAttribute('aria-selected', String(selected));
      tab?.setAttribute('tabindex', selected ? '0' : '-1');
    });
  };
  definitions.forEach(definition => {
    definition.panel.id = `admin-panel-${definition.id}`;
    const tab = element('button');
    tab.type = 'button';
    tab.dataset.tab = definition.id;
    tab.textContent = definition.label;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', definition.panel.id);
    tab.addEventListener('click', () => activate(definition.id));
    list.append(tab);
  });
  root.append(list, ...definitions.map(definition => definition.panel));
  if (initial) activate(initial);
}
