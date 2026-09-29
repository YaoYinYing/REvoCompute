import { getTerms } from '../../api/app-api';
import './legal.css';

export type LegalBlock =
  | { kind: 'heading'; level: 1 | 2 | 3; text: string; id?: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] };

const headingPattern = /^(#{1,3})\s+(.+?)(?:\s+\{#([A-Za-z][\w-]*)\})?$/;
const listPattern = /^(?:([-*])|(\d+)\.)\s+(.+)$/;

export function parseLegalMarkdown(markdown: string): LegalBlock[] {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n');
  const blocks: LegalBlock[] = [];
  for (let index = 0; index < lines.length;) {
    const line = lines[index]!.trim();
    if (!line) { index += 1; continue; }
    const heading = headingPattern.exec(line);
    if (heading) {
      blocks.push({ kind: 'heading', level: heading[1]!.length as 1 | 2 | 3, text: heading[2]!, ...(heading[3] ? { id: heading[3] } : {}) });
      index += 1; continue;
    }
    const firstItem = listPattern.exec(line);
    if (firstItem) {
      const ordered = Boolean(firstItem[2]); const items: string[] = [];
      while (index < lines.length) {
        const item = listPattern.exec(lines[index]!.trim());
        if (!item || Boolean(item[2]) !== ordered) break;
        items.push(item[3]!); index += 1;
      }
      blocks.push({ kind: 'list', ordered, items }); continue;
    }
    const paragraph = [line]; index += 1;
    while (index < lines.length) {
      const next = lines[index]!.trim();
      if (!next || headingPattern.test(next) || listPattern.test(next)) break;
      paragraph.push(next); index += 1;
    }
    blocks.push({ kind: 'paragraph', text: paragraph.join(' ') });
  }
  return blocks;
}

function appendInline(parent: HTMLElement, source: string): void {
  const pattern = /\*\*([^*]+)\*\*/g; let cursor = 0;
  for (const match of source.matchAll(pattern)) {
    const start = match.index ?? 0;
    parent.append(document.createTextNode(source.slice(cursor, start)));
    const strong = document.createElement('strong'); strong.textContent = match[1]!; parent.append(strong);
    cursor = start + match[0].length;
  }
  parent.append(document.createTextNode(source.slice(cursor)));
}

export function renderLegalMarkdown(markdown: string): DocumentFragment {
  const fragment = document.createDocumentFragment();
  for (const block of parseLegalMarkdown(markdown)) {
    if (block.kind === 'heading') {
      const heading = document.createElement(`h${block.level}`); heading.textContent = block.text;
      if (block.id) heading.id = block.id; fragment.append(heading); continue;
    }
    if (block.kind === 'paragraph') {
      const paragraph = document.createElement('p'); appendInline(paragraph, block.text); fragment.append(paragraph); continue;
    }
    const list = document.createElement(block.ordered ? 'ol' : 'ul');
    block.items.forEach(item => { const li = document.createElement('li'); appendInline(li, item); list.append(li); });
    fragment.append(list);
  }
  return fragment;
}

export async function mountTerms(root: HTMLElement): Promise<void> {
  document.title = 'Terms of Service | REvoCompute';
  root.innerHTML = '<main class="legal-page"><article class="legal-document"><p class="loading-state">Loading Terms of Service...</p></article></main>';
  const article = root.querySelector<HTMLElement>('.legal-document')!;
  try {
    const document = await getTerms();
    article.replaceChildren(renderLegalMarkdown(document.markdown));
    article.dataset.version = document.version;
  } catch (error) {
    article.innerHTML = '<div class="inline-state state-error"><h1>Terms unavailable</h1><p data-error></p><a class="secondary-button" href="/compute/register">Return to registration</a></div>';
    article.querySelector<HTMLElement>('[data-error]')!.textContent = error instanceof Error ? error.message : 'Try again after the server is available.';
  }
}
