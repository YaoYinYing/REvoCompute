/*
 * `candidate-collection` ResultView rendering: the declared candidate artifacts, and for
 * sequence candidates the FASTA records they contain, through the shared CandidateSelector.
 *
 * A candidate is presented by its published name and, when it is a sequence collection, by
 * each record's own header and residue count. Nothing here ranks candidates or infers a score.
 */
import { resultFileName, type ResultFile, type ResultView } from '../../api/result-types';
import { t } from '../../app/i18n';
import { artifactCapability, type LocalSourceFiles } from './renderer-registry';
import { CandidateSelector } from './scientific';
import { boundedText } from './molecular/structure-controller';
import type { ResolvedViewSources, ViewRenderer } from './renderer-registry';

export interface FastaRecord { name: string; sequence: string; }

/** Parse FASTA records, keeping the header's own text and the residues as written. */
export function parseFasta(text: string): FastaRecord[] {
  const records: FastaRecord[] = [];
  let current: FastaRecord | null = null;
  for (const line of String(text).split(/\r?\n/)) {
    if (line.startsWith('>')) {
      current = { name: line.slice(1).trim(), sequence: '' };
      records.push(current);
    } else if (current) current.sequence += line.trim();
  }
  return records.filter((record) => record.sequence.length > 0);
}

/** A FASTA artifact's declared media type, or its name, identifies a sequence collection. */
export function isSequenceCollection(file: ResultFile): boolean {
  const mediaType = (file.media_type || '').toLowerCase();
  if (mediaType === 'text/x-fasta' || mediaType === 'application/x-fasta') return true;
  return /(?:^|\/)(?:[^/]*\.(?:fasta|fa|fas|faa)|[^/]*\.a3m)$/i.test(resultFileName(file));
}

/** The most FASTA text read for one candidate collection; a larger file is stated, not truncated. */
const MAX_SEQUENCE_BYTES = 1024 * 1024;

async function fetchText(file: ResultFile, signal: AbortSignal, local?: LocalSourceFiles): Promise<string> {
  // A collection over the bound is not parsed partially: a partial record would be
  // reported with a wrong residue count, and the list would look complete.
  if (file.size > MAX_SEQUENCE_BYTES) throw new Error(t('results.candidates.error.tooLarge', { name: resultFileName(file) }));
  if (local) return local.readUtf8(file.path, MAX_SEQUENCE_BYTES);
  const response = await fetch(file.url, { credentials: 'same-origin', signal, headers: { Range: `bytes=0-${MAX_SEQUENCE_BYTES - 1}` } });
  if (!response.ok && response.status !== 206) throw new Error(t('results.candidates.error.unreadable', { name: resultFileName(file) }));
  // The declared size is not a bound on what is read: a Range-ignoring server
  // answers 200 with the whole body, and a publication can disagree with the
  // manifest. The bytes actually read are bounded, so an oversized body is
  // refused rather than presented as a complete, truncated candidate set.
  const tooLarge = (): Error => new Error(t('results.candidates.error.tooLarge', { name: resultFileName(file) }));
  if (!response.body) {
    const text = await response.text();
    if (new TextEncoder().encode(text).byteLength > MAX_SEQUENCE_BYTES) throw tooLarge();
    return text;
  }
  try { return await boundedText(response.body, MAX_SEQUENCE_BYTES); }
  catch (error) { if ((error as Error).name === 'AbortError') throw error; throw tooLarge(); }
}

/** A structure the page's own stage already draws: this view states it, never remounts it. */
function pageDrawsStructureNote(): HTMLElement {
  const note = document.createElement('p'); note.className = 'result-note';
  note.textContent = t('results.candidates.drawnAbove');
  return note;
}

/** Render a declared `candidate-collection` view through the shared CandidateSelector. */
export function createCandidateCollectionViewRenderer(): ViewRenderer {
  return {
    id: 'candidate-collection',
    async render(view: ResultView, sources: ResolvedViewSources, host: HTMLElement, context) {
      const files = sources.candidates || [];
      const section = document.createElement('section'); section.className = 'candidate-collection-view';
      const heading = document.createElement('h3'); heading.textContent = view.title;
      const controls = document.createElement('div'); controls.className = 'candidate-list';
      // A structure candidate is shown in the workspace's own molecular stage, so the
      // stage element is dedicated: the structure renderer replaces the children of
      // the host it is handed, and the selector must stay beside it.
      const stage = document.createElement('div'); stage.className = 'candidate-stage';
      const detail = document.createElement('div'); detail.className = 'candidate-detail';
      section.append(heading, controls, detail); host.replaceChildren(section);
      if (!files.length) {
        const empty = document.createElement('p'); empty.className = 'result-empty';
        empty.textContent = t('results.candidates.empty'); detail.append(empty);
        return { destroy: () => section.replaceChildren() };
      }

      const sequences = files.filter(isSequenceCollection);
      const records: Array<{ name: string; sequence: string; file: ResultFile }> = [];
      for (const file of sequences) {
        for (const record of parseFasta(await fetchText(file, context.signal, context.localSource))) {
          records.push({ ...record, file });
        }
      }
      if (context.signal.aborted) return { destroy: () => section.replaceChildren() };

      const items = [...records.map((record) => ({ name: record.name, record })), ...files
        .filter((file) => !sequences.includes(file))
        .map((file) => ({ name: resultFileName(file), record: null as null, file }))];
      if (!items.length) {
        const empty = document.createElement('p'); empty.className = 'result-empty';
        empty.textContent = t('results.candidates.empty'); detail.append(empty);
        return { destroy: () => section.replaceChildren() };
      }

      //: Whether this view mounted the shared structure stage, and so owns closing it.
      let ownsStage = false;
      const selector = new CandidateSelector(controls, {
        items,
        label: (item) => item.name,
        onSelect: async (item, _index, request) => {
          detail.replaceChildren();
          const pageDrawsIt = !item.record && Boolean(item.file) && Boolean(context.drawsStructure?.(item.file!));
          const showsStructure = !item.record && Boolean(context.openStructure) && !pageDrawsIt
            && ['structure', 'molecular_structure'].includes(artifactCapability(item.file!));
          // The stage belongs to the selection that opened it: a selection that is
          // not a structure removes it, and invalidates a mount still in flight so
          // it cannot land in a stage the sequence now owns. A view that never
          // opened the shared stage owns nothing to close: the storyboard's own
          // structure may already be mounted in it.
          if (!showsStructure && ownsStage) { stage.remove(); context.closeStructure?.(stage); ownsStage = false; }
          // The page already draws this returned structure in its own stage on the
          // first screen; mounting it here as well would dispossess that stage, so
          // the download link is the whole statement this view makes of it.
          if (!item.record && !showsStructure && pageDrawsIt) detail.append(pageDrawsStructureNote());
          if (!item.record) {
            const file = item.file!;
            const link = document.createElement('a'); link.className = 'result-button result-button-small';
            link.href = file.url; link.setAttribute('download', '');
            link.textContent = t('results.candidates.download', { name: resultFileName(file) });
            detail.append(link);
            if (showsStructure) {
              if (stage.parentNode !== section) section.insertBefore(stage, detail);
              ownsStage = true;
              // A candidate that cannot be shown states why and leaves no empty stage: the
              // selection rejects here, and a superseded mount is not a failure to report.
              try { await context.openStructure!(file, stage); }
              catch (error) {
                if ((error as Error).name === 'AbortError' || !request.current()) return false;
                stage.remove(); ownsStage = false;
                const note = document.createElement('p'); note.className = 'result-empty';
                note.textContent = (error as Error).message || t('results.structureUnavailable');
                detail.append(note);
              }
            }
            return true;
          }
          const facts = document.createElement('dl'); facts.className = 'candidate-facts';
          const length = document.createElement('div');
          const term = document.createElement('dt'); term.textContent = t('results.candidates.length');
          const value = document.createElement('dd'); value.textContent = String(item.record.sequence.length);
          length.append(term, value);
          const sequence = document.createElement('pre'); sequence.className = 'candidate-sequence';
          sequence.textContent = item.record.sequence;
          sequence.setAttribute('aria-label', t('results.candidates.sequence'));
          facts.append(length);
          const download = document.createElement('a'); download.className = 'result-button result-button-small';
          download.href = item.record.file.url; download.setAttribute('download', '');
          download.textContent = t('results.candidates.downloadFile', { name: resultFileName(item.record.file) });
          detail.append(facts, sequence, download);
          return true;
        },
      });
      void selector.select(0);
      return { destroy: () => { selector.destroy(); if (ownsStage) context.closeStructure?.(stage); } };
    },
  };
}
