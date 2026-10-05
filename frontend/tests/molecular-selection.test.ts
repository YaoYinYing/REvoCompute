import { describe, expect, it } from 'vitest';

import { MolecularViewer } from '../src/features/structure/MolecularViewer';

// The residue matcher is the generic selection contract every storyboard shares.
// These cases pin its insertion-code semantics without mounting a viewer.
const residue = (overrides: Partial<Parameters<typeof MolecularViewer.matchesResidue>[0]> = {}) => ({
  entity: '1', authChain: 'A', labelChain: 'A', authSeqId: 42, labelSeqId: 42, insCode: '',
  ...overrides,
});

describe('MolecularViewer.matchesResidue insertion-code semantics', () => {
  it('treats an unspecified insertion code as "any residue at this number"', () => {
    // Regression: a caller that never mentions an insertion code (e.g. a
    // label_seq_id selection) must still match a residue that HAS one.
    expect(MolecularViewer.matchesResidue(residue({ insCode: 'A' }), { chain: 'A', residue: 42, numbering: 'auth_seq_id' })).toBe(true);
    expect(MolecularViewer.matchesResidue(residue({ insCode: '' }), { chain: 'A', residue: 42, numbering: 'auth_seq_id' })).toBe(true);
  });

  it('treats an explicit empty code as "the bare residue only"', () => {
    const selector = { chain: 'A', residue: 42, numbering: 'auth_seq_id' as const, insertionCode: '' };
    expect(MolecularViewer.matchesResidue(residue({ insCode: '' }), selector)).toBe(true);
    expect(MolecularViewer.matchesResidue(residue({ insCode: 'A' }), selector)).toBe(false);
    // Whitespace-only is the same as empty.
    expect(MolecularViewer.matchesResidue(residue({ insCode: '' }), { ...selector, insertionCode: '  ' })).toBe(true);
    expect(MolecularViewer.matchesResidue(residue({ insCode: 'A' }), { ...selector, insertionCode: '  ' })).toBe(false);
  });

  it('matches an exact non-empty insertion code', () => {
    const selector = { chain: 'A', residue: 42, numbering: 'auth_seq_id' as const, insertionCode: 'A' };
    expect(MolecularViewer.matchesResidue(residue({ insCode: 'A' }), selector)).toBe(true);
    expect(MolecularViewer.matchesResidue(residue({ insCode: '' }), selector)).toBe(false);
    expect(MolecularViewer.matchesResidue(residue({ insCode: 'B' }), selector)).toBe(false);
  });

  it('still constrains chain and residue number', () => {
    expect(MolecularViewer.matchesResidue(residue({ authChain: 'B' }), { chain: 'A', residue: 42, numbering: 'auth_seq_id' })).toBe(false);
    expect(MolecularViewer.matchesResidue(residue({ authSeqId: 43 }), { chain: 'A', residue: 42, numbering: 'auth_seq_id' })).toBe(false);
  });
});
