export function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag); node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

export function filePath(file: File): string {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
}

export function matchesExtension(file: File, extensions: string[]): boolean {
  const name = file.name.toLowerCase();
  return extensions.some(extension => name.endsWith(extension.toLowerCase()));
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MiB`;
}

export function parseSequence(raw: string): { name: string; sequence: string; error: string } {
  let value = raw.trim();
  if (!value) return { name: '', sequence: '', error: '' };
  let name = '';
  if (value.startsWith('>')) {
    const records = value.split(/^>/m).filter(Boolean);
    if (records.length !== 1) return { name: '', sequence: '', error: 'Paste exactly one FASTA record.' };
    const lines = records[0]!.split(/\r?\n/); name = lines.shift()!.trim(); value = lines.join('');
  }
  const sequence = value.replace(/\s/g, '').toUpperCase();
  return /^[A-Z]+$/.test(sequence)
    ? { name, sequence, error: '' }
    : { name, sequence: '', error: 'Paste protein letters or one FASTA record.' };
}
