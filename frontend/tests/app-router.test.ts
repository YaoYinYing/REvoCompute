import { describe, expect, it } from 'vitest';
import { protectedRoute, resolveRoute } from '../src/app/router';

describe('application routes', () => {
  it('resolves every frontend-owned route', () => {
    expect(resolveRoute('/runners')).toEqual({ id: 'runners' });
    expect(resolveRoute('/runners/alphafold3/')).toEqual({ id: 'runner-detail', name: 'alphafold3' });
    expect(resolveRoute('/compute/dashboard')).toEqual({ id: 'dashboard' });
    expect(resolveRoute('/compute/create_task')).toEqual({ id: 'create-task' });
    expect(resolveRoute(`/compute/results/${'A'.repeat(32)}`)).toEqual({ id: 'result', taskId: 'a'.repeat(32) });
  });

  it('keeps public discovery separate from authenticated workspaces', () => {
    expect(protectedRoute(resolveRoute('/runners'))).toBe(false);
    expect(protectedRoute(resolveRoute('/runners/example'))).toBe(false);
    expect(protectedRoute(resolveRoute('/compute/dashboard'))).toBe(true);
    expect(resolveRoute('/compute/results/not-a-task')).toEqual({ id: 'not-found' });
    expect(resolveRoute('/runners/%E0%A4%A')).toEqual({ id: 'not-found' });
  });
});
