/** Local display projection only. The original File and submission are never rewritten. */
export interface AlignmentCell {
  symbol: string;
  sourceCharacter: number;
  residue: number | null;
}
export interface AlignmentRow { name: string; cells: AlignmentCell[]; columns: number }
export interface AlignmentPreview { rows: AlignmentRow[]; columns: number | null; limited: boolean; ragged: boolean }

export function alignmentPreview(source: string, a3m: boolean, sourceTruncated = false): AlignmentPreview | null {
  const records = source.replace(/^\uFEFF/, '').trimStart().split(/^>/m);
  if (records.shift() !== '') return null;
  // A sliced prefix cannot establish that its final record is complete.
  if (sourceTruncated) records.pop();
  if (!records.length) return null;
  const rows: AlignmentRow[] = [];
  for (const record of records.slice(0, 8)) {
    const lines = record.split(/\r?\n/); const name = (lines.shift() || '').trim();
    const sequence = lines.join('').replace(/\s/g, '');
    if (!name || !sequence || !/^[A-Za-z.-]+$/.test(sequence)) return null;
    const cells: AlignmentCell[] = []; let residue = 0; let columns = 0;
    for (let index = 0; index < sequence.length; index++) {
      const symbol = sequence[index]!;
      if (/[A-Za-z]/.test(symbol)) residue++;
      if (a3m && /[a-z.]/.test(symbol)) { continue; }
      columns++;
      if (cells.length < 160) cells.push({ symbol: symbol.toUpperCase(), sourceCharacter: index + 1, residue: /[.-]/.test(symbol) ? null : residue });
    }
    if (!columns) return null;
    rows.push({ name, cells, columns });
  }
  const ragged = rows.some(row => row.columns !== rows[0]!.columns);
  return { rows,
    columns: ragged ? null : rows[0]!.columns, ragged,
    limited: sourceTruncated || records.length > 8 || rows.some(row => row.columns > 160) };
}

export function residueTone(symbol: string): string {
  if ('DE'.includes(symbol)) return 'acid';
  if ('KRH'.includes(symbol)) return 'base';
  if ('FWY'.includes(symbol)) return 'aromatic';
  if ('ILMV'.includes(symbol)) return 'hydrophobic';
  return '.-'.includes(symbol) ? 'gap' : 'neutral';
}
