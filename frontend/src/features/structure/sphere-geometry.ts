/** Original fpocket PQR sphere centres (Å) and radii (Å), without geometric inference. */
export interface RecordedSphere { center: [number, number, number]; radius: number; }
export function parseRecordedSpheres(source: string): RecordedSphere[] {
  const records = source.split(/\r?\n/).filter(line => /^(?:ATOM  |HETATM)/.test(line));
  if (!records.length || records.length > 10_000) throw new Error('Alpha-sphere evidence is empty or exceeds the display limit.');
  return records.map(line => {
    const coordinates = [line.slice(30, 38), line.slice(38, 46), line.slice(46, 54)];
    const rawRadius = line.trim().split(/\s+/).at(-1)!;
    const center = coordinates.map(value => value.trim() ? Number(value) : Number.NaN) as [number, number, number];
    const radius = Number(rawRadius);
    if (!center.every(Number.isFinite) || !Number.isFinite(radius) || radius <= 0) throw new Error('Alpha-sphere evidence has invalid recorded coordinates or radii.');
    return { center, radius };
  });
}
