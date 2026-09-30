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
    tab.id = `admin-tab-${definition.id}`;
    tab.dataset.tab = definition.id;
    tab.textContent = definition.label;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', definition.panel.id);
    definition.panel.setAttribute('aria-labelledby', tab.id);
    tab.addEventListener('click', () => activate(definition.id));
    list.append(tab);
  });
  const tabs = [...list.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  tabs.forEach((tab, index) => tab.addEventListener('keydown', event => {
    const offsets: Record<string, number> = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 };
    let target = index;
    if (event.key === 'Home') target = 0;
    else if (event.key === 'End') target = tabs.length - 1;
    else if (event.key in offsets) target = (index + offsets[event.key]! + tabs.length) % tabs.length;
    else return;
    event.preventDefault(); activate(definitions[target]!.id); tabs[target]!.focus();
  }));
  root.append(list, ...definitions.map(definition => definition.panel));
  if (initial) activate(initial);
}
