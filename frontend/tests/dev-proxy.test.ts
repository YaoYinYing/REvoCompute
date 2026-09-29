import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';
import { resolveConfig } from 'vite';

describe('development server configuration', () => {
  it('routes APIs and immutable server resources without proxying frontend pages', async () => {
    const config = await resolveConfig(
      { configFile: resolve(import.meta.dirname, '../vite.config.ts') },
      'serve',
    );
    const proxy = config.server.proxy || {};

    expect(proxy['/compute/api']).toMatchObject({ target: 'http://127.0.0.1:8080', changeOrigin: false });
    expect(proxy['/compute/dashboard']).toBeUndefined();
    expect(proxy['/compute/create_task']).toBeUndefined();
    expect(proxy['/compute/login']).toBeUndefined();
    expect(proxy['/compute/profile']).toBeUndefined();
    expect(proxy['/compute/terms']).toBeUndefined();
    expect(proxy['/compute/logo.svg']).toBeUndefined();
    expect(proxy['/favicon.ico']).toBeUndefined();
    expect(proxy['/openapi.json']).toMatchObject({ target: 'http://127.0.0.1:8080', changeOrigin: false });
    expect(proxy['/skills.md']).toMatchObject({ target: 'http://127.0.0.1:8080', changeOrigin: false });
    expect(proxy['/compute/results']).toBeUndefined();
    expect(config.appType).toBe('spa');
    expect(config.base).toBe('/');
  });
});
