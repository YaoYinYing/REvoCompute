import type { CurrentUser } from '../../api/app-api';
import type { AppShell } from '../../app/shell';
import { ConfigurationAdmin } from './configuration/ConfigurationAdmin';
import { FleetAdmin } from './fleet/FleetAdmin';
import { LogsAdmin } from './logs/LogsAdmin';
import { element, text } from './shared/dom';
import { UserAdmin } from './users/UserAdmin';
import './admin.css';

export type AdminRoute = 'admin-fleet' | 'admin-users' | 'admin-configuration' | 'admin-logs';

const headings: Record<AdminRoute, [string, string]> = {
  'admin-fleet': ['Runner fleet', 'Derived readiness, transient capacity, access, and typed corrective actions for every enabled Runner family.'],
  'admin-users': ['User control', 'Manage accounts, Runner access, and GPU credit operations.'],
  'admin-configuration': ['Runtime configuration', 'Manage task availability, resource policy, and infrastructure evidence.'],
  'admin-logs': ['Server logs', 'Inspect bounded active logs and managed rotated archives.'],
};

export async function mountAdmin(
  outlet: HTMLElement,
  route: AdminRoute,
  shell: AppShell,
  user: CurrentUser,
): Promise<void> {
  if (user.role !== 'admin') {
    outlet.replaceChildren(element('section', 'route-error', [text('p', '403', 'page-kicker'), text('h1', 'Administrator access required'), text('p', 'This view is available only to administrators.') ]));
    return;
  }
  const [title, description] = headings[route];
  const root = element('main', 'admin-page');
  root.append(element('header', 'page-heading', [element('div', '', [text('h1', title), text('p', description)])]));
  const workspace = element('div', 'admin-workspace'); root.append(workspace); outlet.replaceChildren(root);
  if (route === 'admin-fleet') await new FleetAdmin(shell).mount(workspace);
  else if (route === 'admin-users') await new UserAdmin(shell, user).mount(workspace);
  else if (route === 'admin-configuration') await new ConfigurationAdmin(shell).mount(workspace);
  else await new LogsAdmin(shell).mount(workspace);
}
