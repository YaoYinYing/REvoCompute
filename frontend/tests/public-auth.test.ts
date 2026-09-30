import { afterEach, describe, expect, it, vi } from 'vitest';

import { createApiKey, getRegistrationCapability, getTerms, login, resetPassword, revokeApiKey, verifyEmail } from '../src/api/app-api';
import { clearSessionCredential } from '../src/app/session';
import { safeReturnTo } from '../src/features/auth/index';

afterEach(() => { clearSessionCredential(); vi.unstubAllGlobals(); });

describe('public authentication contracts', () => {
  it('accepts only same-origin absolute-path return targets', () => {
    expect(safeReturnTo('?return_to=%2Fcompute%2Fprofile%3Ftab%3Dmetrics', 'https://compute.example')).toBe('/compute/profile?tab=metrics');
    expect(safeReturnTo('?return_to=https%3A%2F%2Fevil.example', 'https://compute.example')).toBe('/compute/dashboard');
    expect(safeReturnTo('?return_to=%2F%2Fevil.example', 'https://compute.example')).toBe('/compute/dashboard');
    expect(safeReturnTo('?return_to=%2F%5Cevil.example', 'https://compute.example')).toBe('/compute/dashboard');
  });

  it('uses the login token in memory for API-key lifecycle mutations', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ token: 'ephemeral', username: 'ada' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ api_key: 'shown-once', message: 'Store it.' }), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: 'API key revoked' }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await login('ada', 'secret');
    await expect(createApiKey()).resolves.toMatchObject({ api_key: 'shown-once' });
    await expect(revokeApiKey()).resolves.toEqual({ message: 'API key revoked' });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const createHeaders = fetchMock.mock.calls[1]?.[1]?.headers as Headers;
    expect(createHeaders.get('Authorization')).toBe('Bearer ephemeral');
  });

  it('targets the canonical registration, reset, verification, and legal APIs', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ enabled: true, email_available: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: 'updated' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: 'verified', email: 'a@example.org', registration_pending: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ document: 'terms', version: 'sha256:abc', markdown: '# Terms' }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await getRegistrationCapability(); await resetPassword('opaque', 'long-password'); await verifyEmail('opaque'); await getTerms();
    expect(fetchMock.mock.calls.map(call => call[0])).toEqual([
      '/compute/api/auth/registration', '/compute/api/auth/reset-password', '/compute/api/auth/verify-email', '/compute/api/legal/terms',
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({ token: 'opaque', password: 'long-password' });
  });
});
