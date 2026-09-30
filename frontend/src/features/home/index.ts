import { Check, Clipboard } from 'lucide';
import { createIcons } from 'lucide';
import type { AppShell } from '../../app/shell';
import './home.css';

export function mountHome(root: HTMLElement, shell: AppShell): void {
  document.title = 'REvoDesign | Human-guided enzyme redesign';
  root.innerHTML = `
    <main class="home-page">
      <section class="home-hero">
        <div class="home-hero-copy">
          <p class="page-kicker">Human-guided protein engineering</p>
          <h1>REvoDesign</h1>
          <p class="home-offer">Enzyme redesign guided by structure, evolution, and scientific judgment.</p>
          <p class="home-summary">Bring structural context, phylogenetic evidence, human expertise, and managed computation into one connected workflow. Turn complex evidence into practical, testable mutations.</p>
          <div class="home-actions"><a class="primary-button" href="/compute/dashboard">Open REvoCompute</a><a class="secondary-button" href="/runners">Browse runners</a></div>
        </div>
        <figure class="evidence-flow" aria-label="Structural, evolutionary, and computational evidence converge through designer judgment into candidate mutations">
          <div class="evidence-plate">
            <figcaption>Evidence-guided design</figcaption>
            <div class="evidence-lanes">
              <div><span>01</span><strong>Structure</strong><small>Pockets, surfaces, ligands</small></div>
              <div><span>02</span><strong>Evolution</strong><small>Conservation, co-evolution</small></div>
              <div><span>03</span><strong>Computation</strong><small>Prediction, scoring</small></div>
            </div>
            <div class="evidence-converge" aria-hidden="true"><span></span><span></span><span></span></div>
            <div class="evidence-decision"><span>Designer judgment</span><strong>Testable mutations</strong></div>
          </div>
        </figure>
        <aside class="agent-guide" aria-labelledby="agent-guide-title">
          <div><h2 id="agent-guide-title">Connect an AI agent</h2><p>Use the stable guide for task discovery, submission, and result retrieval.</p></div>
          <a data-agent-url href="/skills.md"><code></code></a>
          <button class="icon-button" type="button" data-copy-guide title="Copy agent API guide URL" aria-label="Copy agent API guide URL"><i data-lucide="clipboard"></i></button>
          <span class="sr-only" data-copy-status role="status" aria-live="polite"></span>
        </aside>
      </section>

      <section class="home-principles" id="approach">
        <header><p class="page-kicker">The approach</p><h2>Evidence narrows the search. Human judgment directs it.</h2><p>REvoDesign supports semi-rational enzyme engineering. Computation reduces a vast design space while scientific context and experimental priorities stay central.</p></header>
        <div class="principle-list">
          <article><span>01</span><h3>Structural context</h3><p>Study solvent exposure, binding pockets, substrates, cofactors, and mutation sites directly inside PyMOL.</p></article>
          <article><span>02</span><h3>Evolutionary evidence</h3><p>Use conservation profiles, sequence clustering, and residue co-evolution to identify plausible design space.</p></article>
          <article><span>03</span><h3>Human supervision</h3><p>Select, reject, compare, and prioritize mutations with the designer's knowledge kept firmly in the loop.</p></article>
        </div>
      </section>

      <section class="home-workflow" id="workflow">
        <header><p class="page-kicker">One connected workflow</p><h2>From molecular context to testable candidates.</h2></header>
        <ol><li><span>01</span><strong>Explore</strong><p>Inspect the structure and identify relevant regions in PyMOL.</p></li><li><span>02</span><strong>Propose</strong><p>Combine structural observations, evolutionary constraints, and design intent.</p></li><li><span>03</span><strong>Compute</strong><p>Run managed prediction, scoring, sequence, structure, and analysis workflows.</p></li><li><span>04</span><strong>Evaluate</strong><p>Compare candidates and reduce the design space for wet-lab validation.</p></li></ol>
      </section>

      <section class="home-products" aria-label="REvoDesign tools">
        <article><p class="page-kicker">Interactive design environment</p><h2>REvoDesign for PyMOL</h2><p>Explore structures, define designable regions, supervise mutation selection, and evaluate candidates in molecular context.</p><a href="https://yaoyinying.github.io/REvoDesign/user-guide/installation/">Install the plugin</a></article>
        <article><p class="page-kicker">Managed scientific computing</p><h2>REvoCompute</h2><p>Submit reproducible CPU and GPU workflows, follow execution, and inspect structures, tables, logs, and artifacts.</p><a href="/compute/dashboard">Open the workspace</a></article>
      </section>

      <section class="home-closing"><blockquote>Computation proposes.<br>Evidence constrains.<br><em>The designer decides.</em></blockquote><div><a class="primary-button" href="/compute/dashboard">Open REvoCompute</a><a class="secondary-button" href="https://yaoyinying.github.io/REvoCompute/">Read the documentation</a></div></section>
      <footer><span>REvoDesign / REvoCompute</span><span>Open-source tools for human-guided enzyme engineering.</span></footer>
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
}
