import { describe, expect, it } from 'vitest';
import { adminRoute, protectedRoute, publicShellRoute, resolveRoute } from '../src/app/router';

describe('application routes', () => {
  it('resolves every frontend-owned route', () => {
    expect(resolveRoute('/')).toEqual({ id: 'home' });
    expect(resolveRoute('/api-docs')).toEqual({ id: 'api-docs' });
    expect(resolveRoute('/compute/login')).toEqual({ id: 'login' });
    expect(resolveRoute('/compute/register')).toEqual({ id: 'register' });
    expect(resolveRoute('/compute/reset_password')).toEqual({ id: 'reset-password' });
    expect(resolveRoute('/compute/user_verify')).toEqual({ id: 'verify-email' });
    expect(resolveRoute('/compute/terms')).toEqual({ id: 'terms' });
    expect(resolveRoute('/runners')).toEqual({ id: 'runners' });
    expect(resolveRoute('/runners/alphafold3/')).toEqual({ id: 'runner-detail', name: 'alphafold3' });
    expect(resolveRoute('/compute/dashboard')).toEqual({ id: 'dashboard' });
    expect(resolveRoute('/compute/create_task')).toEqual({ id: 'create-task' });
    expect(resolveRoute(`/compute/results/${'A'.repeat(32)}`)).toEqual({ id: 'result', taskId: 'a'.repeat(32) });
    expect(resolveRoute('/compute/profile')).toEqual({ id: 'profile' });
    expect(resolveRoute('/compute/runner_fleet')).toEqual({ id: 'admin-fleet' });
    expect(resolveRoute('/compute/user_control')).toEqual({ id: 'admin-users' });
    expect(resolveRoute('/compute/configuration')).toEqual({ id: 'admin-configuration' });
    expect(resolveRoute('/compute/logs')).toEqual({ id: 'admin-logs' });
  });

  it('keeps public discovery separate from authenticated workspaces', () => {
    expect(protectedRoute(resolveRoute('/runners'))).toBe(false);
    expect(protectedRoute(resolveRoute('/runners/example'))).toBe(false);
    expect(protectedRoute(resolveRoute('/compute/login'))).toBe(false);
    expect(protectedRoute(resolveRoute('/compute/dashboard'))).toBe(true);
    expect(protectedRoute(resolveRoute('/compute/profile'))).toBe(true);
    expect(adminRoute(resolveRoute('/compute/runner_fleet'))).toBe(true);
    expect(protectedRoute(resolveRoute('/compute/runner_fleet'))).toBe(true);
    expect(adminRoute(resolveRoute('/compute/user_control'))).toBe(true);
    expect(publicShellRoute(resolveRoute('/compute/terms'))).toBe(true);
    expect(publicShellRoute(resolveRoute('/runners'))).toBe(false);
    expect(resolveRoute('/compute/results/not-a-task')).toEqual({ id: 'not-found' });
    expect(resolveRoute('/runners/%E0%A4%A')).toEqual({ id: 'not-found' });
  });
});
