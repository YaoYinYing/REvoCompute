import { getTaskDiagnosticExcerpt, getTaskDiagnostics } from '../../api/app-api';
import { t } from '../../app/i18n';
import './diagnostics.css';

/** The server bounds one retained excerpt to 64 KiB; the line list needs no virtualization. */
const MAX_MATCHES = 1000;
/** A pathological line-per-byte excerpt still renders at most this many recent lines. */
const MAX_RENDERED_LINES = 10_000;

function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag); if (text != null) node.textContent = text; return node;
}

interface Match { line: number; start: number; end: number }

function findMatches(lines: string[], query: string): { matches: Match[]; capped: boolean } {
  // The pattern is an escaped literal, never user-authored regex, so matching
  // is a linear scan over text the server already bounded.
  const pattern = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
  const matches: Match[] = [];
  for (let line = 0; line < lines.length; line += 1) {
    const text = lines[line] ?? '';
    pattern.lastIndex = 0;
    let hit: RegExpExecArray | null;
    while ((hit = pattern.exec(text)) !== null) {
      if (matches.length === MAX_MATCHES) return { matches, capped: true };
      if (hit[0].length === 0) pattern.lastIndex += 1;
      else matches.push({ line, start: hit.index, end: hit.index + hit[0].length });
    }
  }
  return { matches, capped: false };
}

function paint(body: HTMLElement, text: string, matches: Match[]): void {
  if (!matches.length) { body.textContent = text; return; }
  const nodes: Array<Text | HTMLElement> = [];
  let at = 0;
  for (const match of matches) {
    if (match.start > at) nodes.push(document.createTextNode(text.slice(at, match.start)));
    nodes.push(element('mark', text.slice(match.start, match.end)));
    at = match.end;
  }
  if (at < text.length) nodes.push(document.createTextNode(text.slice(at)));
  body.replaceChildren(...nodes);
}

/**
 * Add on-demand reading and literal search over one retained excerpt.
 *
 * The fetched bytes are the same bounded, redacted text the download offers;
 * the server stays authoritative for the 64 KiB bound, redaction and ownership.
 */
function addRetainedExcerpt(
  section: HTMLElement, stream: string, url: string, preview: HTMLElement, truncatedNote: HTMLElement, signal: AbortSignal,
): void {
  const toggle = element('button', t('diagnostics.showExcerpt')); toggle.type = 'button';
  const region = element('div'); region.className = 'task-diagnostic-excerpt'; region.hidden = true;
  region.id = `task-diagnostic-excerpt-${stream}`;
  toggle.setAttribute('aria-expanded', 'false'); toggle.setAttribute('aria-controls', region.id);

  const searchBar = element('div'); searchBar.className = 'task-diagnostic-search';
  const label = element('label', t('diagnostics.search')); label.htmlFor = `task-diagnostic-search-${stream}`;
  const input = element('input'); input.type = 'search'; input.id = label.htmlFor;
  input.className = 'task-diagnostic-search-input'; input.placeholder = t('diagnostics.searchPlaceholder');
  const previous = element('button', t('diagnostics.searchPrev')); previous.type = 'button'; previous.disabled = true;
  const next = element('button', t('diagnostics.searchNext')); next.type = 'button'; next.disabled = true;
  searchBar.append(label, input, previous, next);

  const status = element('p'); status.className = 'task-diagnostic-search-status'; status.setAttribute('aria-live', 'polite');
  const note = element('p', t('diagnostics.excerptLines')); note.className = 'task-diagnostic-note';
  const cappedNote = element('p'); cappedNote.className = 'task-diagnostic-note task-diagnostic-capped'; cappedNote.hidden = true;
  const linesHost = element('div'); linesHost.className = 'task-diagnostic-lines'; linesHost.tabIndex = 0;
  linesHost.setAttribute('role', 'region'); linesHost.setAttribute('aria-label', t('diagnostics.excerptLabel', { stream }));
  const loading = element('p', t('diagnostics.excerptLoading')); loading.className = 'task-diagnostic-note'; loading.hidden = true;
  const failure = element('p', t('diagnostics.excerptFailed')); failure.className = 'task-diagnostic-error'; failure.hidden = true;
  region.append(searchBar, status, note, cappedNote, linesHost, loading, failure);
  section.append(toggle, region);

  let loaded = false;
  let busy = false;
  let shown: string[] = [];
  const rows: HTMLElement[] = [];
  const bodies: HTMLElement[] = [];
  const highlighted = new Set<number>();
  let matches: Match[] = [];
  let active = -1;
  let capped = false;

  const show = (visible: boolean): void => {
    region.hidden = !visible;
    preview.hidden = visible; truncatedNote.hidden = visible;
    toggle.setAttribute('aria-expanded', String(visible));
    toggle.textContent = visible ? t('diagnostics.hideExcerpt') : t('diagnostics.showExcerpt');
  };

  const setNavigation = (enabled: boolean): void => {
    previous.disabled = !enabled; next.disabled = !enabled;
  };

  const select = (position: number): void => {
    if (!matches.length) return;
    active = ((position % matches.length) + matches.length) % matches.length;
    const line = matches[active]!.line;
    for (const row of rows) row.classList.remove('is-current');
    const row = rows[line];
    if (row) { row.classList.add('is-current'); row.scrollIntoView({ block: 'center' }); }
    status.textContent = t(capped ? 'diagnostics.searchCapped' : 'diagnostics.searchCount',
      { current: active + 1, total: matches.length });
  };

  const runSearch = (): void => {
    for (const line of highlighted) {
      const body = bodies[line]; const text = shown[line];
      if (body && text !== undefined) body.textContent = text;
    }
    for (const row of rows) row.classList.remove('is-current');
    highlighted.clear(); matches = []; active = -1; capped = false;
    const query = input.value;
    if (!query) { status.textContent = ''; setNavigation(false); return; }
    const found = findMatches(shown, query);
    matches = found.matches; capped = found.capped;
    let index = 0;
    while (index < matches.length) {
      const line = matches[index]!.line;
      const group: Match[] = [];
      while (index < matches.length && matches[index]!.line === line) { group.push(matches[index]!); index += 1; }
      const body = bodies[line];
      if (body) { paint(body, shown[line] ?? '', group); highlighted.add(line); }
    }
    if (!matches.length) { status.textContent = t('diagnostics.searchNone'); setNavigation(false); return; }
    setNavigation(true); select(0);
  };

  input.addEventListener('input', runSearch);
  input.addEventListener('keydown', (event) => {
    const key = event as KeyboardEvent;
    if (key.key === 'Enter') {
      if (typeof key.preventDefault === 'function') key.preventDefault();
      if (matches.length) select(active + (key.shiftKey ? -1 : 1));
    } else if (key.key === 'Escape') { input.value = ''; runSearch(); }
  });
  previous.addEventListener('click', () => select(active - 1));
  next.addEventListener('click', () => select(active + 1));

  const render = (text: string): void => {
    const all = text.split('\n');
    if (all.length > 1 && all[all.length - 1] === '') all.pop();
    const start = Math.max(0, all.length - MAX_RENDERED_LINES);
    shown = all.slice(start);
    cappedNote.hidden = start === 0;
    cappedNote.textContent = t('diagnostics.excerptCapped', { count: shown.length });
    for (let index = 0; index < shown.length; index += 1) {
      const row = element('div'); row.className = 'task-diagnostic-line';
      const gutter = element('span', String(start + index + 1)); gutter.className = 'task-diagnostic-gutter';
      gutter.setAttribute('aria-hidden', 'true');
      const body = element('span'); body.className = 'task-diagnostic-line-text'; body.textContent = shown[index] ?? '';
      row.append(gutter, body); linesHost.append(row); rows.push(row); bodies.push(body);
    }
  };

  toggle.addEventListener('click', () => {
    if (busy) return;
    if (loaded) { show(region.hidden); return; }
    // The button stays enabled so a keyboard reader does not lose focus; the
    // busy guard, not disabled state, prevents a duplicate request.
    busy = true; failure.hidden = true; loading.hidden = false;
    getTaskDiagnosticExcerpt(url, signal).then((text) => {
      if (signal.aborted) return;
      render(text); loaded = true; loading.hidden = true;
      preview.hidden = true; truncatedNote.hidden = true; show(true);
    }).catch((error: Error) => {
      if (signal.aborted || error.name === 'AbortError') return;
      loading.hidden = true; failure.hidden = false;
    }).finally(() => { busy = false; });
  });
}

/** One bounded read per opening/retry; excerpts load only on request. Route/dialog disposal aborts pending work. */
export function mountTaskDiagnostics(host: HTMLElement, taskId: string, signal: AbortSignal): void {
  host.classList.add('task-diagnostics'); host.setAttribute('aria-label', t('diagnostics.title'));
  const load = async (): Promise<void> => {
    host.replaceChildren(element('h3', t('diagnostics.title')), element('p', t('diagnostics.loading')));
    host.setAttribute('aria-busy', 'true');
    try {
      const evidence = await getTaskDiagnostics(taskId, signal); if (signal.aborted) return;
      host.replaceChildren(element('h3', t('diagnostics.title')), element('p', evidence.summary));
      const facts = element('dl'); facts.className = 'task-diagnostic-facts';
      const fact = (label: string, value: string): void => { facts.append(element('dt', label), element('dd', value)); };
      fact(t('diagnostics.classification'), evidence.reason_code || t('diagnostics.unknown'));
      fact(t('diagnostics.stage'), evidence.stage || t('diagnostics.unknown'));
      fact(t('diagnostics.exit'), evidence.exit_code == null ? t('diagnostics.unknown') : `${evidence.exit_code} (${evidence.exit_code_source})`);
      if (evidence.scheduler_state) fact(t('diagnostics.scheduler'), evidence.scheduler_state);
      host.append(facts);
      if (evidence.availability === 'expired') host.append(element('p', t('diagnostics.expired')));
      if (!evidence.logs.length) host.append(element('p', t('diagnostics.noLogs')));
      for (const log of evidence.logs) {
        const section = element('section'); const heading = element('h4', t('diagnostics.log', { stream: log.stream }));
        const pre = element('pre', log.preview); pre.tabIndex = 0; pre.setAttribute('aria-label', heading.textContent!);
        const download = element('a', t('diagnostics.download', { stream: log.stream })); download.href = log.download_url; download.download = '';
        const truncated = element('p', t('diagnostics.truncated')); truncated.hidden = !log.truncated;
        section.append(heading, pre);
        if (log.truncated) section.append(truncated);
        if (log.truncated) addRetainedExcerpt(section, log.stream, log.download_url, pre, truncated, signal);
        section.append(download); host.append(section);
      }
      host.append(element('p', t('diagnostics.context')));
    } catch (error) {
      if (signal.aborted || (error as Error).name === 'AbortError') return;
      const retry = element('button', t('diagnostics.retry')); retry.type = 'button'; retry.addEventListener('click', () => void load(), { once: true });
      host.replaceChildren(element('h3', t('diagnostics.title')), element('p', t('diagnostics.loadFailed')), retry);
    } finally { if (!signal.aborted) host.setAttribute('aria-busy', 'false'); }
  };
  void load();
}
