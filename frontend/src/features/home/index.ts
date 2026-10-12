import { Check, Clipboard } from 'lucide';
import { createIcons } from 'lucide';
import { getMcpCapability } from '../../api/app-api';
import type { AppShell } from '../../app/shell';
import './home.css';

export function mountHome(root: HTMLElement, shell: AppShell): void {
  document.title = 'REvoCompute | Managed scientific computation';
  root.innerHTML = `
    <main class="home-page">
      <section class="home-hero">
        <div class="home-hero-copy">
          <p class="page-kicker">Scientific computation, managed</p>
          <h1>REvoCompute</h1>
          <p class="home-offer">Run the methods behind protein and enzyme design, then inspect what they return.</p>
          <p class="home-summary">Give a method its inputs and REvoCompute runs it as a reproducible Runner on managed infrastructure, returning structures, tables, models, and artifacts you can examine. It is the compute companion to REvoDesign.</p>
          <div class="home-actions"><a class="primary-button" href="/compute/dashboard">Open the workspace</a><a class="secondary-button" href="/runners">Browse runners</a></div>
        </div>
        <figure class="evidence-flow" aria-label="Scientific inputs run through a reproducible Runner to produce inspectable results">
          <div class="evidence-plate">
            <figcaption>From input to artifact</figcaption>
            <div class="evidence-lanes">
              <div><span>01</span><strong>Sequence</strong><small>FASTA and protein letters</small></div>
              <div><span>02</span><strong>Structure</strong><small>PDB and mmCIF coordinates</small></div>
              <div><span>03</span><strong>Design</strong><small>Regions, mutations, parameters</small></div>
            </div>
            <div class="evidence-converge" aria-hidden="true"><span></span><span></span><span></span></div>
            <div class="evidence-decision"><span>Reproducible Runner</span><strong>Inspectable result</strong></div>
          </div>
        </figure>
        <aside class="agent-guide" aria-labelledby="agent-guide-title">
          <div><h2 id="agent-guide-title">Connect an AI agent</h2><p>Discover, submit, and retrieve tasks over a stable guide.</p></div>
          <a data-agent-url href="/skills.md"><code></code></a>
          <button class="icon-button" type="button" data-copy-guide title="Copy agent API guide URL" aria-label="Copy agent API guide URL"><i data-lucide="clipboard"></i></button>
          <span class="sr-only" data-copy-status role="status" aria-live="polite"></span>
        </aside>
      </section>

      <section class="home-principles" id="approach">
        <header><p class="page-kicker">How it works</p><h2>Declared contracts, reproducible runs, readable results.</h2></header>
        <div class="principle-list">
          <article><span>01</span><h3>Named inputs</h3><p>Each Runner declares its data roles and formats, so you always know what a method expects before you run it.</p></article>
          <article><span>02</span><h3>Reproducible runtimes</h3><p>Runners execute in pinned, self-contained images with validated dependency stacks, not on an ad-hoc workstation.</p></article>
          <article><span>03</span><h3>Inspectable results</h3><p>Every run returns a manifest of structures, tables, and artifacts, alongside the files and logs behind them.</p></article>
        </div>
      </section>

      <section class="home-workflow" id="workflow">
        <header><p class="page-kicker">One path through a run</p><h2>From a method to a result you can read.</h2></header>
        <ol><li><span>01</span><strong>Choose</strong><p>Open a Runner and read its scientific contract: inputs, parameters, and what it produces.</p></li><li><span>02</span><strong>Provide</strong><p>Supply the inputs its roles declare, either as files or as pasted sequence.</p></li><li><span>03</span><strong>Run</strong><p>Submit once. REvoCompute validates, queues, and runs it on managed infrastructure.</p></li><li><span>04</span><strong>Inspect</strong><p>Open the result, examine the structures and tables, and download the artifacts.</p></li></ol>
      </section>

      <section class="home-products" aria-label="REvoCompute and REvoDesign">
        <article><p class="page-kicker">Managed scientific computing</p><h2>REvoCompute</h2><p>Run the predictions, scoring, sequence, and structure methods you choose, then inspect the structures, tables, logs, and artifacts they return.</p><a href="/compute/dashboard">Open the workspace</a></article>
        <article><p class="page-kicker">Interactive design environment</p><h2>REvoDesign for PyMOL</h2><p>Explore structures, define designable regions, supervise mutation selection, and evaluate candidates in molecular context, then hand computation to REvoCompute.</p><a href="https://yaoyinying.github.io/REvoDesign/user-guide/installation/">Install the plugin</a></article>
      </section>

      <section class="home-closing"><blockquote>Computation runs.<br>Evidence returns.<br><em>You decide what it means.</em></blockquote><div><a class="primary-button" href="/compute/dashboard">Open the workspace</a><a class="secondary-button" href="https://yaoyinying.github.io/REvoCompute/">Read the documentation</a></div></section>
      <footer><span>REvoCompute / REvoDesign</span><span>Open-source tools for reproducible protein engineering.</span></footer>
    </main>`;
  const url = new URL('/skills.md', location.origin).href;
  const link = root.querySelector<HTMLAnchorElement>('[data-agent-url]')!;
  const button = root.querySelector<HTMLButtonElement>('[data-copy-guide]')!;
  const status = root.querySelector<HTMLElement>('[data-copy-status]')!;
  link.querySelector('code')!.textContent = url;
  link.title = url;
  createIcons({ icons: { Clipboard }, root: button });
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(url);
      button.innerHTML = '<i data-lucide="check"></i>';
      createIcons({ icons: { Check }, root: button });
      status.textContent = 'Agent API guide URL copied.';
      window.setTimeout(() => {
        button.innerHTML = '<i data-lucide="clipboard"></i>';
        createIcons({ icons: { Clipboard }, root: button }); status.textContent = '';
      }, 1600);
    } catch {
      status.textContent = 'Select the URL to copy it manually.'; link.focus(); shell.notify('Select the URL to copy it manually.');
    }
  });
  void applyAgentCapability(root);
}

/*
 * The "Connect an AI agent" entry states one deployment fact: whether this
 * deployment actually serves the MCP endpoint.
 *
 * A public Home page is seen before a reader has any way to tell code from a
 * running deployment, so "the repository has MCP" must never be presented as
 * "this server speaks MCP". The entry keeps the always-available agent API guide
 * — /skills.md is served by every deployment — and only *adds* the MCP endpoint
 * once the deployment's own capability read says it answers. A read that fails,
 * is slow, or reports the surface off leaves the documentation-only state; the
 * upgrade to the live endpoint happens only on an affirmative read.
 */
async function applyAgentCapability(root: HTMLElement): Promise<void> {
  const aside = root.querySelector<HTMLElement>('.agent-guide');
  const capability = await getMcpCapability().catch(() => null);
  if (!aside || !capability?.enabled || !capability.endpoint) return;
  const endpoint = new URL(capability.endpoint, location.origin).href;
  aside.dataset.mcpState = 'enabled';
  const copy = aside.querySelector('p');
  if (copy) copy.textContent = 'Discover, submit, and retrieve tasks over MCP, or connect over the stable HTTP guide.';
  const mcpLink = document.createElement('a');
  mcpLink.className = 'agent-guide-endpoint'; mcpLink.href = capability.endpoint;
  mcpLink.setAttribute('aria-label', `MCP endpoint: ${endpoint}`);
  const code = document.createElement('code'); code.textContent = endpoint; mcpLink.append(code);
  const guide = aside.querySelector('[data-agent-url]');
  if (guide) guide.after(mcpLink); else aside.append(mcpLink);
}
