export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); this.name = 'ApiError'; }
}

let bearerToken: string | null = null;
let tokenRequest: Promise<string> | null = null;
export const sessionExpiredEvent = 'revocompute:session-expired';

function authorizedPath(url: string): string {
  if (!url.startsWith('/') || url.startsWith('//') || url.includes('\\')) {
    throw new Error('Authorized requests must be same-origin paths.');
  }
  const base = new URL('https://revocompute.invalid/');
  const resolved = new URL(url, base);
  if (resolved.origin !== base.origin) throw new Error('Authorized requests must be same-origin paths.');
  return `${resolved.pathname}${resolved.search}${resolved.hash}`;
}

function notifySessionExpired(): void {
  clearSessionCredential();
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(sessionExpiredEvent));
}

async function responseError(response: Response): Promise<ApiError> {
  const payload = await response.clone().json().catch(() => ({})) as Record<string, unknown>;
  return new ApiError(String(payload.error || payload.message || `Request failed (HTTP ${response.status})`), response.status);
}

export async function requestJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { ...init, credentials: 'same-origin' });
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}

async function mintToken(force = false): Promise<string> {
  if (force) bearerToken = null;
  if (bearerToken) return bearerToken;
  if (!tokenRequest) {
    tokenRequest = requestJson<{ token: string }>('/compute/api/auth/token')
      .then(({ token }) => { bearerToken = token; return token; })
      .catch(error => { if (error instanceof ApiError && error.status === 401) notifySessionExpired(); throw error; })
      .finally(() => { tokenRequest = null; });
  }
  return tokenRequest;
}

/** Perform a same-origin mutation with an ephemeral bearer credential. */
export async function authorizedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const path = authorizedPath(url);
  const send = async (force: boolean): Promise<Response> => {
    const headers = new Headers(init.headers); headers.set('Authorization', `Bearer ${await mintToken(force)}`);
    return fetch(path, { ...init, headers, credentials: 'same-origin' });
  };
  let response = await send(false);
  if (response.status === 403) {
    const payload = await response.clone().json().catch(() => ({})) as Record<string, unknown>;
    if (String(payload.error || '').includes('Bearer token')) response = await send(true);
  }
  if (response.status === 401) notifySessionExpired();
  return response;
}

export async function authorizedJson<T>(url: string, init: RequestInit = {}): Promise<T> {
  const response = await authorizedFetch(url, init);
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}

/** Keep a login response credential in memory for this document only. */
export function establishSessionCredential(token: string): void {
  bearerToken = token;
  tokenRequest = null;
}

export function clearSessionCredential(): void { bearerToken = null; tokenRequest = null; }
