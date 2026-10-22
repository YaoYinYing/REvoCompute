/** Make an ENDMDL-only multi-frame PDB readable by Mol*'s PDB trajectory parser.
 *
 * Mol* 5.12.0 (``mol-model-formats/structure/pdb/to-cif``) starts a new model only
 * at a ``MODEL `` record; it has no ENDMDL handling. RFdiffusion's ``*_traj.pdb``
 * files delimit every frame with ENDMDL and write no MODEL records, so the parser
 * would read the whole file as one model and every later frame would disappear.
 * A file that already carries MODEL records is returned unchanged.
 */
export function normalizePdbFrameDelimiters(text: string): string {
  return /^MODEL\s/m.test(text) ? text : text.replace(/^ENDMDL[ \t]*\r?$(?=\s*\S)/gm, 'ENDMDL\nMODEL        1');
}
