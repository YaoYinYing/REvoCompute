/*
 * The Administration destinations the shell navigates to as pages.
 *
 * The left navigation is the product's information architecture, and each entry
 * here is a destination the server must serve: the page route, its authorization
 * boundary, and the shell that renders it are server-owned. This file is the
 * frontend half of that declaration — `revocompute/routes.py::ADMIN_PAGE_ROUTES`
 * is the server half, and `tests/server/test_admin_page_routes.py` holds the two
 * together. A destination the navigation links to but the server does not serve
 * is a production 404, so the link and the route are declared once, here and
 * there, rather than in places that drift apart.
 */

export interface AdminDestination {
  /** Page path the shell links to and the server serves. */
  readonly path: string;
  /** Lucide icon name used by the navigation rail. */
  readonly icon: string;
  /** Translation key for the navigation label. */
  readonly label: string;
}

export const ADMIN_DESTINATIONS: readonly AdminDestination[] = [
  { path: '/compute/runner_fleet', icon: 'server-cog', label: 'shell.admin.fleet' },
  { path: '/compute/user_control', icon: 'users-round', label: 'shell.admin.users' },
  { path: '/compute/logs', icon: 'file-text', label: 'shell.admin.logs' },
  { path: '/compute/configuration', icon: 'settings', label: 'shell.admin.configuration' },
];
