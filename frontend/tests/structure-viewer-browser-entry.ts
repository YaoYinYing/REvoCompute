// Copyright (c) 2026 The REvoDesign Developers.
// Distributed under the terms of the GNU General Public License v3.0.
// SPDX-License-Identifier: GPL-3.0-only
//
// Boots the real ``MolecularViewer`` inside a browser contract page. The viewer
// is imported unchanged; the page supplies the read-only artifact bytes and the
// mount options, and this entry only reports when the viewer can be inspected.
import { MolecularViewer } from '../src/features/structure/MolecularViewer';

declare global {
  interface Window {
    __structureData?: { data: string; format: 'pdb' | 'mmcif'; label?: string };
    __structureOptions?: Record<string, unknown>;
    __structureViewer?: MolecularViewer;
  }
}

const host = document.getElementById('structureEntryHost');
if (host && window.__structureData) {
  void MolecularViewer.mount(host, window.__structureOptions || {})
    .then(async (viewer) => {
      window.__structureViewer = viewer;
      await viewer.loadStructure(window.__structureData!);
      document.documentElement.dataset.structureReady = 'true';
    })
    .catch((error) => {
      document.documentElement.dataset.structureError = String((error as Error)?.stack || error);
    });
}

export {};
