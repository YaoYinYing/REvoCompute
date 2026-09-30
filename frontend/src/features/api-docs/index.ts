import SwaggerUI from 'swagger-ui-dist/swagger-ui-es-bundle.js';
import 'swagger-ui-dist/swagger-ui.css';
import './api-docs.css';

export function mountApiDocs(root: HTMLElement): void {
  document.title = 'API documentation | REvoCompute';
  root.innerHTML = `
    <main class="api-docs-page">
      <header class="api-docs-heading"><p class="page-kicker">OpenAPI 3.1</p><h1>REvoCompute API</h1><p>Explore task discovery, submission, and result retrieval. Authorize with a session token or API key to try protected operations against this server.</p></header>
      <section class="api-docs-host" aria-label="Interactive API reference"></section>
    </main>`;
  SwaggerUI({
    url: '/openapi.json',
    domNode: root.querySelector<HTMLElement>('.api-docs-host')!,
    deepLinking: true,
    persistAuthorization: false,
    validatorUrl: null,
  });
}
