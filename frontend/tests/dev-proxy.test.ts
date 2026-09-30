import { resolve } from 'node:path';
import type { AddressInfo } from 'node:net';

import { describe, expect, it } from 'vitest';
import { createServer, resolveConfig } from 'vite';

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

  it('serves resolved brand assets instead of the SPA fallback', async () => {
    const server = await createServer({
      configFile: resolve(import.meta.dirname, '../vite.config.ts'),
      server: { port: 0, strictPort: false },
    });
    try {
      await server.listen();
      const address = server.httpServer?.address() as AddressInfo;
      const origin = `http://127.0.0.1:${address.port}`;
      const html = await fetch(origin).then(response => response.text());
      expect(html).toContain('href="/logo.svg"');
      const logo = await fetch(`${origin}/logo.svg`);
      expect(logo.headers.get('content-type')).toContain('image/svg+xml');
      expect(await logo.text()).toContain('<svg');
    } finally {
      await server.close();
    }
  });
});
