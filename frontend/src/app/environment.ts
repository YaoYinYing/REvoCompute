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
  if (pending) return pending;
  const request = fetch('/compute/api/environment', { credentials: 'same-origin' })
    .then(async (response) => {
      if (!response.ok) return null;
      const payload = await response.json().catch(() => null) as Record<string, unknown> | null;
      if (!payload || typeof payload !== 'object') return null;
      const { version, demo_mode, execution, notice } = payload;
      // A malformed body is not a profile. Accepting a partial payload would
      // default a demo deployment served through a captive portal to the
      // production answer; only the complete documented shape resolves.
      if (version !== 1 || typeof demo_mode !== 'boolean') return null;
      if (execution !== 'available' && execution !== 'preview_only') return null;
      const parsedExecution: EnvironmentCapability['execution'] = execution === 'preview_only' ? 'preview_only' : 'available';
      return {
        version,
        demo_mode,
        execution: parsedExecution,
        ...(typeof notice === 'string' && notice ? { notice } : {}),
      };
    })
    .catch(() => null)
    .then((environment) => {
      // Only a resolved answer is cached. A failed read clears the in-flight
      // promise so the next caller retries instead of inheriting the failure.
      if (environment) current = environment;
      else pending = null;
      return environment;
    });
  pending = request;
  return request;
}
