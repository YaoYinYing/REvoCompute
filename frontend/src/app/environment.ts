/*
 * The deployment profile the browser must state honestly.
 *
 * `GET /compute/api/environment` is a public, read-only fact owned by the
 * Server. The demo profile serves the canonical catalog and recorded results
 * but refuses every submission, so the shell labels that difference once
 * instead of inferring it from an empty catalog. A read that does not answer
 * resolves to `null`: an outage is not the production answer, and no caller may
 * cache it as one. The Server's submission refusal remains the boundary.
 */

export interface EnvironmentCapability {
  version: number;
  demo_mode: boolean;
  execution: 'available' | 'preview_only';
  notice?: string;
}

let current: EnvironmentCapability | null = null;
let pending: Promise<EnvironmentCapability | null> | null = null;

/** Read the deployment profile, or `null` when the read produced no answer. */
export function loadEnvironment(): Promise<EnvironmentCapability | null> {
  if (current) return Promise.resolve(current);
  if (!pending) {
    pending = fetch('/compute/api/environment', { credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) return null;
        const payload = await response.json().catch(() => null) as Partial<EnvironmentCapability> | null;
        if (!payload || typeof payload !== 'object') return null;
        const parsed: EnvironmentCapability = {
          version: typeof payload.version === 'number' ? payload.version : 1,
          demo_mode: payload.demo_mode === true,
          execution: payload.execution === 'preview_only' ? 'preview_only' : 'available',
          ...(typeof payload.notice === 'string' && payload.notice ? { notice: payload.notice } : {}),
        };
        return parsed;
      })
      .catch(() => null)
      .then((environment) => {
        // Only a resolved answer is cached. A failed read clears the in-flight
        // promise so the next caller retries instead of inheriting the failure.
        if (environment) current = environment;
        else pending = null;
        return environment;
      });
  }
  return pending;
}
