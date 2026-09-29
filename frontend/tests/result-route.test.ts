import { describe, expect, it } from 'vitest';

import { resultTaskId } from '../src/app/result-route.js';

describe('resultTaskId', () => {
  it('reconstructs the normalized task identity from a Result URL', () => {
    expect(resultTaskId('/compute/results/ABCDEF0123456789ABCDEF0123456789')).toBe(
      'abcdef0123456789abcdef0123456789',
    );
    expect(resultTaskId('/compute/results/abcdef0123456789abcdef0123456789/')).toBe(
      'abcdef0123456789abcdef0123456789',
    );
  });

  it('rejects legacy and malformed routes', () => {
    expect(resultTaskId('/compute/dashboard')).toBeNull();
    expect(resultTaskId('/compute/results/not-a-task')).toBeNull();
    expect(resultTaskId('/compute/results/abcdef0123456789abcdef0123456789/files')).toBeNull();
  });
});
